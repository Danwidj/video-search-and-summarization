# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the privacy blur: head-region maths, the pixelation and the evidence write sites."""

from collections.abc import Generator
from pathlib import Path
import tempfile
from typing import Any

import cv2
import numpy as np
import pytest

from vss_agents.utils import privacy_blur
from vss_agents.utils.crop_evidence import BudgetedDetector
from vss_agents.utils.crop_evidence import CropCallBudget
from vss_agents.utils.crop_evidence import CropEvidenceService
from vss_agents.utils.crop_evidence import Detection
from vss_agents.utils.crop_evidence import FakeZoomNamer
from vss_agents.utils.crop_evidence import InMemoryEvidenceStore
from vss_agents.utils.privacy_blur import PrivacySummary
from vss_agents.utils.privacy_blur import blur_frame
from vss_agents.utils.privacy_blur import centre_inside
from vss_agents.utils.privacy_blur import head_region
from vss_agents.utils.privacy_blur import overlaps
from vss_agents.utils.privacy_blur import pad_box
from vss_agents.utils.privacy_blur import pixel_box
from vss_agents.utils.privacy_blur import track_heads_at
from vss_agents.utils.privacy_blur import unique_regions
from vss_agents.utils.track_evidence import Sample
from vss_agents.utils.track_evidence import Track
from vss_agents.utils.track_evidence import TrackingOutcome
from vss_agents.utils.track_evidence import TrackingRequest

WIDTH, HEIGHT = 200, 100


def _texture(seed: int = 7) -> np.ndarray:
    """A frame of coarse random blocks: detail a pixelation visibly removes and JPEG keeps."""
    rng = np.random.default_rng(seed)
    blocks = rng.integers(0, 256, size=(HEIGHT // 4, WIDTH // 4, 3), dtype=np.uint8)
    return np.ascontiguousarray(np.repeat(np.repeat(blocks, 4, axis=0), 4, axis=1))


class TestHeadRegionMaths:
    def test_the_head_is_the_top_30_percent_raised_and_widened_by_10_percent(self) -> None:
        assert head_region((200, 400, 600, 500)) == (160, 390, 320, 510)

    def test_the_head_region_is_clamped_to_the_frame(self) -> None:
        assert head_region((0, 0, 1000, 1000)) == (0, 0, 300, 1000)
        assert head_region((10, 980, 410, 1000)) == (0, 978, 130, 1000)

    def test_padding_grows_every_side_and_clamps(self) -> None:
        assert pad_box((100, 100, 200, 300), 0.25) == (75, 50, 225, 350)
        assert pad_box((0, 900, 100, 1000), 0.5) == (0, 850, 150, 1000)

    def test_centre_inside_and_overlap(self) -> None:
        assert centre_inside((100, 100, 200, 200), (0, 0, 150, 150))
        assert not centre_inside((100, 100, 200, 200), (0, 0, 140, 140))
        assert overlaps((0, 0, 100, 100), (99, 99, 200, 200))
        assert not overlaps((0, 0, 100, 100), (100, 0, 200, 100))  # touching edges share no area

    def test_track_heads_come_from_every_track_with_a_sample_near_the_second(self) -> None:
        near = Track("1", [Sample(0.0, (0, 0, 500, 100), 0.9), Sample(1.0, (100, 0, 600, 100), 0.9)])
        far = Track("2", [Sample(5.0, (0, 500, 500, 600), 0.9)])
        assert track_heads_at([near, far], 0.9) == [head_region((100, 0, 600, 100))]
        assert track_heads_at([near, far], 3.0) == []
        assert track_heads_at([Track("3", [])], 0.0) == []

    def test_unique_regions_drop_duplicates_and_empty_boxes(self) -> None:
        assert unique_regions([(0, 0, 10, 10), (0, 0, 10, 10), (5, 5, 5, 9), (1, 2, 3)]) == [(0, 0, 10, 10)]

    def test_pixel_boxes_round_outwards_and_clamp(self) -> None:
        assert pixel_box((101, 101, 199, 199), 200, 100) == (10, 20, 20, 40)
        assert pixel_box((0, 990, 1000, 1000), 205, 103) == (0, 202, 103, 205)


class TestBlurFrame:
    def test_only_the_regions_change_and_the_input_frame_is_kept(self) -> None:
        frame = _texture()
        original = frame.copy()
        blurred = blur_frame(frame, [(0, 0, 500, 500)])
        assert np.array_equal(frame, original)
        assert np.array_equal(blurred[50:, :], frame[50:, :])
        assert np.array_equal(blurred[:, 100:], frame[:, 100:])
        assert not np.array_equal(blurred[:50, :100], frame[:50, :100])

    def test_a_region_is_reduced_to_at_most_six_blocks_across(self) -> None:
        blurred = blur_frame(_texture(), [(0, 0, 600, 300)])  # 60 x 60 pixels
        patch = blurred[:60, :60].reshape(-1, 3)
        assert len(np.unique(patch, axis=0)) <= privacy_blur.PIXEL_BLOCKS**2

    def test_no_regions_is_a_plain_copy(self) -> None:
        frame = _texture()
        assert np.array_equal(blur_frame(frame, []), frame)


# --- the evidence write sites ------------------------------------------------------------------------------------


@pytest.fixture
def textured_video() -> Generator[Path]:
    """Two seconds at 10 fps of one textured frame, so every second shows the same picture."""
    with tempfile.NamedTemporaryFile(suffix=".avi", delete=False) as handle:
        path = Path(handle.name)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    frame = _texture()
    for _ in range(20):
        writer.write(frame)
    writer.release()
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


PERSON_BOX = [200, 200, 800, 500]  # [ymin, xmin, ymax, xmax] of the person and of the object (0..1000)
HEAD_BOX = [200, 300, 400, 400]  # a head inside the person box

# Everything at second 0, so a person's head applies to every item's frame.
REPORT: dict[str, Any] = {
    "incident": {"type": "theft"},
    "entities": [{"entity_id": "E1", "type": "human", "description": "man", "timestamp_seconds": 0, "label": "man"}],
    "instruments": [
        {"instrument_id": "I1", "entity_id": "E1", "name": "bag", "description": "bag", "timestamp_seconds": 0}
    ],
    "assets": [],
}


class RecordingDetector:
    """Answers the locate query with PERSON_BOX and a head query with ``head`` (None: nothing found)."""

    def __init__(self, head: list[int] | None = HEAD_BOX) -> None:
        self.head = head
        self.queries: list[str] = []

    def is_available(self) -> bool:
        return True

    def detect(self, frame: np.ndarray, query: str) -> list[Detection]:
        self.queries.append(query)
        if query.startswith("the head of"):
            return [Detection(box=list(self.head), score=1.0)] if self.head else []
        return [Detection(box=list(PERSON_BOX), score=0.9)]


def _tracking(*tracks: Track) -> TrackingRequest:
    async def runner(video_ref: object, *, sensor_id: str, **_: object) -> TrackingOutcome:
        return TrackingOutcome(tracks=list(tracks))

    return TrackingRequest(sensor_id="s", runner=runner)


async def _run(
    video: Path,
    *,
    detector: Any = None,
    privacy: PrivacySummary | None = None,
    tracking: TrackingRequest | None = None,
    namer: FakeZoomNamer | None = None,
) -> tuple[dict[str, dict], InMemoryEvidenceStore]:
    store = InMemoryEvidenceStore()
    service = CropEvidenceService(detector=detector or RecordingDetector(), store=store, namer=namer)
    entries = await service.process_incident_report(
        video_ref=video,
        video_id="v",
        video_key="uploads/a.mp4",
        report=REPORT,
        batch_id="run-1",
        tracking=tracking,
        zoom_names=namer is not None,
        privacy=privacy,
    )
    return {entry["item_id"]: entry for entry in entries}, store


def _decode(data: bytes | None) -> np.ndarray:
    assert data is not None
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).astype(np.int16)


def _difference(a: np.ndarray, b: np.ndarray, region: tuple[int, int, int, int]) -> float:
    y0, x0, y1, x1 = region
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


class TestEvidenceWriteSites:
    @pytest.mark.asyncio
    async def test_without_the_flag_nothing_is_blurred_and_entries_are_unchanged(self, textured_video: Path) -> None:
        detector = RecordingDetector()
        entries, _ = await _run(textured_video, detector=detector)
        assert all("blur_regions" not in entry for entry in entries.values())
        assert not any(query.startswith("the head of") for query in detector.queries)

    @pytest.mark.asyncio
    async def test_the_detector_head_is_blurred_in_every_frame_and_crop_at_that_second(
        self, textured_video: Path
    ) -> None:
        plain, plain_store = await _run(textured_video)
        privacy = PrivacySummary()
        detector = RecordingDetector()
        entries, store = await _run(textured_video, detector=detector, privacy=privacy)

        head = privacy_blur.pad_box(HEAD_BOX, privacy_blur.DETECTED_HEAD_PADDING)
        assert detector.queries.count("the head of man") == 1
        assert privacy.head_queries == 1 and privacy.detector_heads == 1
        for item_id in ("E1", "I1"):
            entry = entries[item_id]
            assert entry["blur_regions"] == [list(head)]
            frame = _decode(store.images[entry["frame"]])
            before = _decode(plain_store.images[plain[item_id]["frame"]])
            y0, x0, y1, x1 = pixel_box(head, WIDTH, HEIGHT)
            assert _difference(frame, before, (y0, x0, y1, x1)) > 20  # the head is pixelated
            assert _difference(frame, before, (y1 + 5, 0, HEIGHT, WIDTH)) < 6  # below it, only JPEG noise
            # the crop is cut from the blurred frame: it differs from the plain crop where the head overlaps it
            assert store.images[entry["image"]] != plain_store.images[plain[item_id]["image"]]
        assert privacy.frames == 2 and privacy.regions == 2 and privacy.failed == 0

    @pytest.mark.asyncio
    async def test_a_track_that_covers_the_person_needs_no_head_query_and_every_track_is_blurred(
        self, textured_video: Path
    ) -> None:
        person = Track("1", [Sample(0.0, tuple(PERSON_BOX), 0.95)])
        bystander = Track("2", [Sample(0.1, (0, 700, 400, 900), 0.9)])  # never matched to a report entity
        privacy = PrivacySummary()
        detector = RecordingDetector()
        request = _tracking(person, bystander)
        entries, _ = await _run(textured_video, detector=detector, privacy=privacy, tracking=request)

        assert not any(query.startswith("the head of") for query in detector.queries)
        assert privacy.track_heads == 1 and privacy.head_queries == 0
        expected = [list(head_region(PERSON_BOX)), list(head_region((0, 700, 400, 900)))]
        assert entries["E1"]["track"]  # matched and re-cut at the best moment, which is blurred as well
        assert sorted(entries["E1"]["blur_regions"]) == sorted(expected)
        assert sorted(entries["I1"]["blur_regions"]) == sorted(expected)

    @pytest.mark.asyncio
    async def test_no_detector_head_falls_back_to_the_top_of_the_persons_box(self, textured_video: Path) -> None:
        privacy = PrivacySummary()
        entries, _ = await _run(textured_video, detector=RecordingDetector(head=None), privacy=privacy)
        located = entries["E1"]["bounding_box"]
        assert entries["E1"]["blur_regions"] == [list(head_region(located))]
        assert privacy.box_heads == 1 and privacy.detector_heads == 0

    @pytest.mark.asyncio
    async def test_a_detected_head_outside_the_person_is_not_trusted(self, textured_video: Path) -> None:
        privacy = PrivacySummary()
        entries, _ = await _run(textured_video, detector=RecordingDetector(head=[0, 900, 100, 1000]), privacy=privacy)
        assert entries["E1"]["blur_regions"] == [list(head_region(entries["E1"]["bounding_box"]))]
        assert privacy.box_heads == 1

    @pytest.mark.asyncio
    async def test_the_head_query_draws_on_the_crop_call_budget_and_a_full_cap_falls_back(
        self, textured_video: Path
    ) -> None:
        budget = CropCallBudget(2)  # the two locate calls; the head query is refused
        privacy = PrivacySummary()
        entries, _ = await _run(textured_video, detector=BudgetedDetector(RecordingDetector(), budget), privacy=privacy)
        assert budget.summary()["refused_by_cap"] == 1
        assert privacy.head_queries == 1 and privacy.box_heads == 1
        assert entries["E1"]["blur_regions"]

    @pytest.mark.asyncio
    async def test_a_failed_blur_stores_no_image_at_all(
        self, textured_video: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(frame: np.ndarray, regions: object) -> np.ndarray:
            raise RuntimeError("no memory")

        monkeypatch.setattr(privacy_blur, "blur_frame", broken)
        privacy = PrivacySummary()
        entries, store = await _run(textured_video, privacy=privacy)
        assert store.images == {}
        assert all(entry["frame"] is None and "privacy blur failed" in entry["image_gap"] for entry in entries.values())
        assert privacy.failed == 2

    @pytest.mark.asyncio
    async def test_the_second_look_still_sees_the_unblurred_close_up(self, textured_video: Path) -> None:
        plain_namer, blurred_namer = FakeZoomNamer(), FakeZoomNamer()
        await _run(textured_video, namer=plain_namer)
        await _run(textured_video, namer=blurred_namer, privacy=PrivacySummary())

        def by_name(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(calls, key=lambda call: call["name"])

        assert by_name(blurred_namer.calls) == by_name(plain_namer.calls)  # the same unblurred close-up, item by item

    def test_the_summary_names_where_each_head_came_from(self) -> None:
        summary = PrivacySummary(regions=3, frames=2, track_heads=1, detector_heads=1, head_queries=1)
        assert summary.to_dict() == {
            "blur_faces": True,
            "regions": 3,
            "frames": 2,
            "heads": {"track": 1, "detector": 1, "box": 0, "none": 0},
            "head_queries": 1,
            "failed": 0,
        }
