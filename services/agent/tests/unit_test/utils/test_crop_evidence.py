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

"""Unit tests for crop_evidence utility and CropEvidenceService (MVP2 VM Step 3)."""

from collections.abc import Generator
import io
from pathlib import Path
import tempfile
from typing import ClassVar
from unittest.mock import MagicMock
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from vss_agents.utils.crop_evidence import BudgetedDetector
from vss_agents.utils.crop_evidence import CropCallBudget
from vss_agents.utils.crop_evidence import CropCallCapReachedError
from vss_agents.utils.crop_evidence import CropEvidenceService
from vss_agents.utils.crop_evidence import CropResult
from vss_agents.utils.crop_evidence import DefaultDetector
from vss_agents.utils.crop_evidence import Detection
from vss_agents.utils.crop_evidence import FakeDetector
from vss_agents.utils.crop_evidence import InMemoryEvidenceStore
from vss_agents.utils.crop_evidence import R2EvidenceStore
from vss_agents.utils.crop_evidence import apply_box_padding
from vss_agents.utils.crop_evidence import crop_evidence_item
from vss_agents.utils.crop_evidence import encode_jpeg
from vss_agents.utils.crop_evidence import evidence_items
from vss_agents.utils.crop_evidence import evidence_key
from vss_agents.utils.crop_evidence import extract_frame
from vss_agents.utils.crop_evidence import get_crop_evidence_service
from vss_agents.utils.crop_evidence import next_run_batch_id
from vss_agents.utils.crop_evidence import normalize_box
from vss_agents.utils.crop_evidence import set_crop_evidence_service


@pytest.fixture
def tiny_video_path() -> Generator[Path]:
    """Generate a tiny 20-frame (2-second at 10fps) video fixture."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        video_path = Path(temp_file.name)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps = 10.0
    width, height = 120, 80
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))

    # Frame 0-9: blue background with white rectangle in center
    for _ in range(10):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (255, 0, 0)  # Blue
        frame[20:60, 30:90] = (255, 255, 255)  # White box
        writer.write(frame)

    # Frame 10-19: green background with red rectangle in center
    for _ in range(10):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (0, 255, 0)  # Green
        frame[10:50, 40:80] = (0, 0, 255)  # Red box
        writer.write(frame)

    writer.release()

    try:
        yield video_path
    finally:
        if video_path.exists():
            video_path.unlink()


class TestEvidenceKey:
    """Test the never-overwritten evidence key layout."""

    def test_canonical_key_format(self) -> None:
        assert evidence_key("uploads/clip.mp4", "run-1", "E1") == "evidence/uploads/clip.mp4/run-1/E1.jpg"

    def test_item_ids_are_unique_across_types_so_no_collection_folder(self) -> None:
        keys = {evidence_key("v", "b", item_id) for item_id in ("E1", "I1", "A1")}
        assert len(keys) == 3

    def test_batch_ids_count_up_from_the_highest_existing_run(self) -> None:
        assert next_run_batch_id([]) == "run-1"
        assert next_run_batch_id(["run-1", "run-3", "edit-9", "x"]) == "run-4"

    @pytest.mark.asyncio
    async def test_in_memory_store_names_the_next_run_per_video(self) -> None:
        store = InMemoryEvidenceStore()
        assert await store.next_batch_id("uploads/a.mp4") == "run-1"
        await store.put_image("evidence/uploads/a.mp4/run-1/E1.jpg", b"x")
        await store.put_image("evidence/uploads/a.mp4.bak/run-7/E1.jpg", b"x")
        assert await store.next_batch_id("uploads/a.mp4") == "run-2"

    @pytest.mark.asyncio
    async def test_r2_store_refuses_to_overwrite_and_lists_batches_by_prefix(self) -> None:
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {
                "CommonPrefixes": [
                    {"Prefix": "evidence/uploads/a.mp4/run-1/"},
                    {"Prefix": "evidence/uploads/a.mp4/run-2/"},
                ]
            }
        ]
        store = R2EvidenceStore(bucket="b", client=client)
        await store.put_image("evidence/uploads/a.mp4/run-3/E1.jpg", b"x")
        assert client.put_object.call_args.kwargs["IfNoneMatch"] == "*"
        assert await store.next_batch_id("uploads/a.mp4") == "run-3"
        assert client.get_paginator.return_value.paginate.call_args.kwargs["Prefix"] == "evidence/uploads/a.mp4/"


class TestBoxPaddingAndNormalization:
    """Test 5% padding clamping and coordinate normalization."""

    def test_padding_calculation(self) -> None:
        # Box [100, 200, 300, 400] on 1000x1000 frame -> bw=200, bh=200.
        # 5% padding = 10 px margin.
        c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding([100, 200, 300, 400], frame_w=1000, frame_h=1000)
        assert (c_ymin, c_xmin, c_ymax, c_xmax) == (90, 190, 310, 410)

    def test_clamping_to_frame_boundaries(self) -> None:
        # Box at origin [0, 0, 100, 100] -> left/top clamped to 0.
        c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding([0, 0, 100, 100], frame_w=1000, frame_h=1000)
        assert c_ymin == 0
        assert c_xmin == 0
        assert c_ymax == 105
        assert c_xmax == 105

        # Box at bottom right [900, 900, 1000, 1000] -> bottom/right clamped to frame max.
        c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding([900, 900, 1000, 1000], frame_w=1000, frame_h=1000)
        assert c_ymin == 895
        assert c_xmin == 895
        assert c_ymax == 1000
        assert c_xmax == 1000

    def test_normalize_box(self) -> None:
        norm = normalize_box(c_ymin=50, c_xmin=100, c_ymax=150, c_xmax=300, frame_w=1000, frame_h=500)
        assert norm == [100, 100, 300, 300]

    def test_apply_box_padding_invalid_dimensions(self) -> None:
        with pytest.raises(ValueError, match="Expected 4 bounding box coordinates"):
            apply_box_padding([10, 20], frame_w=100, frame_h=100)


class TestFrameExtractionAndEncoding:
    """Test video frame extraction and JPEG encoding."""

    def test_extract_frame_valid(self, tiny_video_path: Path) -> None:
        frame_t0 = extract_frame(tiny_video_path, timestamp_seconds=0)
        assert frame_t0 is not None
        assert frame_t0.shape == (80, 120, 3)
        # Blue background at t=0
        assert frame_t0[0, 0, 0] > 200

        frame_t1 = extract_frame(tiny_video_path, timestamp_seconds=1)
        assert frame_t1 is not None
        assert frame_t1.shape == (80, 120, 3)
        # Green background at t=1
        assert frame_t1[0, 0, 1] > 200

    def test_extract_frame_nonexistent_file(self) -> None:
        frame = extract_frame("/path/does/not/exist.mp4", timestamp_seconds=0)
        assert frame is None

    def test_encode_jpeg_quality(self) -> None:
        sample_img = np.zeros((50, 50, 3), dtype=np.uint8)
        jpeg_bytes = encode_jpeg(sample_img, quality=85)
        assert jpeg_bytes is not None
        assert len(jpeg_bytes) > 0
        # Valid JPEG header
        assert jpeg_bytes[:2] == b"\xff\xd8"


class TestCropEvidenceItem:
    """Test crop_evidence_item standalone function."""

    def test_crop_with_fake_detector(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(
            detections=[
                Detection(box=[250, 250, 750, 750], score=0.92, label="person"),
            ]
        )
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=detector,
        )
        assert isinstance(result, CropResult)
        assert result.score == 0.92
        assert result.frame_size == (120, 80)
        assert len(result.normalized_box) == 4
        assert result.image_bytes[:2] == b"\xff\xd8"

    def test_whole_frame_fallback_when_no_box(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[])
        assert crop_evidence_item(tiny_video_path, 0, "weapon", detector=detector) is None
        result = crop_evidence_item(tiny_video_path, 0, "weapon", detector=detector, whole_frame_fallback=True)
        assert result is not None
        assert result.normalized_box == [0, 0, 1000, 1000]
        assert result.score == 0.0
        assert result.frame_size == (120, 80)
        assert result.image_bytes[:2] == b"\xff\xd8"

    def test_crop_picks_best_box(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(
            detections=[
                Detection(box=[100, 100, 200, 200], score=0.40, label="crowbar"),
                Detection(box=[200, 200, 600, 600], score=0.88, label="crowbar"),
                Detection(box=[150, 150, 300, 300], score=0.65, label="crowbar"),
            ]
        )
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=1,
            label="crowbar",
            detector=detector,
        )
        assert result is not None
        assert result.score == 0.88

    def test_crop_returns_none_when_no_detections(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[])
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="unknown",
            detector=detector,
        )
        assert result is None

    def test_crop_returns_none_when_detector_unavailable(self, tiny_video_path: Path) -> None:
        detector = DefaultDetector(api_key="")
        assert not detector.is_available()
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=detector,
        )
        assert result is None

    def test_crop_returns_none_when_detector_is_none(self, tiny_video_path: Path) -> None:
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=None,
        )
        assert result is None

    def test_crop_returns_none_for_invalid_bounding_box(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[Detection(box=[500, 500, 200, 200], score=0.9, label="person")])
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=detector,
        )
        assert result is None


class TestEvidenceStoreAdapters:
    """Test EvidenceStore port and in-memory adapter."""

    @pytest.mark.asyncio
    async def test_in_memory_store_put_and_get(self) -> None:
        store = InMemoryEvidenceStore()
        key = "evidence/Video1/batch/E1.jpg"
        data = b"\xff\xd8\xff\xe0test_image"

        stored_key = await store.put_image(key, data)
        assert stored_key == key

        retrieved = await store.get_image(key)
        assert retrieved == data

        non_existent = await store.get_image("evidence/missing.jpg")
        assert non_existent is None

    @pytest.mark.asyncio
    async def test_r2_store_puts_and_gets_image(self) -> None:
        client = MagicMock()
        client.get_object.return_value = {"Body": io.BytesIO(b"jpeg-bytes")}
        store = R2EvidenceStore(bucket="bucket", client=client)

        key = await store.put_image("evidence/V1/batch/E1.jpg", b"jpeg-bytes")

        assert key == "evidence/V1/batch/E1.jpg"
        client.put_object.assert_called_once_with(
            Bucket="bucket", Key=key, Body=b"jpeg-bytes", ContentType="image/jpeg", IfNoneMatch="*"
        )
        assert await store.get_image(key) == b"jpeg-bytes"

    @pytest.mark.asyncio
    async def test_r2_store_get_image_returns_none_for_missing_key(self) -> None:
        class NoSuchKeyError(Exception):
            response: ClassVar[dict[str, dict[str, str]]] = {"Error": {"Code": "NoSuchKey"}}

        client = MagicMock()
        client.get_object.side_effect = NoSuchKeyError()
        store = R2EvidenceStore(bucket="bucket", client=client)

        assert await store.get_image("evidence/missing.jpg") is None


class TestDefaultDetector:
    """Test the remote-VLM-backed open-vocabulary detector."""

    def _frame(self) -> np.ndarray:
        return np.zeros((80, 120, 3), dtype=np.uint8)

    def test_detect_converts_vlm_box_to_ymin_xmin_ymax_xmax(self) -> None:
        detector = DefaultDetector(api_key="k", base_url="https://vlm.example/v1")
        reply = MagicMock()
        reply.json.return_value = {
            "choices": [{"message": {"content": '```json\n{"bbox_2d": [100, 200, 300, 400], "label": "knife"}\n```'}}]
        }
        with patch("vss_agents.utils.crop_evidence.httpx.post", return_value=reply) as post:
            detections = detector.detect(self._frame(), "knife")

        assert detections == [Detection(box=[200, 100, 400, 300], score=1.0, label="knife")]
        assert post.call_args.args[0] == "https://vlm.example/v1/chat/completions"
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer k"}

    def test_detect_returns_nothing_when_item_not_visible(self) -> None:
        detector = DefaultDetector(api_key="k")
        reply = MagicMock()
        reply.json.return_value = {"choices": [{"message": {"content": '{"bbox_2d": null}'}}]}
        with patch("vss_agents.utils.crop_evidence.httpx.post", return_value=reply):
            assert detector.detect(self._frame(), "unicorn") == []

    def test_a_call_budget_counts_every_http_attempt_including_retries(self) -> None:
        limited = MagicMock(status_code=429, headers={"retry-after": "0"})
        limited.json.return_value = {}
        budget = CropCallBudget(2)
        detector = DefaultDetector(api_key="k").with_call_budget(budget)
        with (
            patch("vss_agents.utils.crop_evidence.httpx.post", return_value=limited) as post,
            patch("vss_agents.utils.crop_evidence.time.sleep"),
            pytest.raises(CropCallCapReachedError),
        ):
            detector.detect(self._frame(), "knife")
        assert post.call_count == 2  # the third attempt was refused before it was sent
        assert budget.summary() == {
            "cap": 2,
            "calls": 2,
            "refused_by_cap": 1,
            "cap_reached": True,
            "tokens": 0,
            "calls_without_usage": 0,  # a 429 carries no usage and is not billed
        }

    def test_a_budgeted_copy_leaves_the_shared_detector_unbudgeted_and_records_tokens(self) -> None:
        reply = MagicMock(status_code=200)
        reply.json.return_value = {
            "choices": [{"message": {"content": '{"bbox_2d": null}'}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 20},
        }
        shared = DefaultDetector(api_key="k")
        budget = CropCallBudget(5)
        with patch("vss_agents.utils.crop_evidence.httpx.post", return_value=reply):
            shared.with_call_budget(budget).detect(self._frame(), "knife")
            shared.detect(self._frame(), "knife")
        assert shared.call_budget is None
        assert budget.calls == 1 and budget.tokens == 920 and budget.calls_without_usage == 0

    def test_a_cap_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CropCallBudget(0)

    def test_detect_without_credentials_makes_no_call(self) -> None:
        detector = DefaultDetector(api_key="")
        with patch("vss_agents.utils.crop_evidence.httpx.post") as post:
            assert detector.detect(self._frame(), "knife") == []
        post.assert_not_called()


REPORT = {
    "incident": {"title": "Burglary", "type": "burglary"},
    "entities": [
        {
            "entity_id": "E1",
            "type": "human",
            "description": "Suspect in hoodie",
            "timestamp_seconds": 0,
            "first_seen_seconds": 0,
            "last_seen_seconds": 2,
            "label": "person",
        }
    ],
    "instruments": [
        {
            "instrument_id": "I1",
            "entity_id": "E1",
            "name": "crowbar",
            "description": "Heavy metal tool",
            "threat_level": 3,
            "timestamp_seconds": 1,
            "label": "crowbar",
        }
    ],
    "assets": [
        {
            "asset_id": "A1",
            "name": "cash register",
            "description": "Store register",
            "timestamp_seconds": 1,
            "label": "cash register",
        }
    ],
}


class TestEvidenceItems:
    def test_lists_entities_instruments_and_assets_with_the_evidence_columns(self) -> None:
        items = evidence_items(REPORT)
        assert [(i["item_type"], i["item_id"], i["item_name"]) for i in items] == [
            ("entity", "E1", "human"),
            ("instrument", "I1", "crowbar"),
            ("asset", "A1", "cash register"),
        ]
        instrument = items[1]
        assert instrument["threat_level"] == 3 and instrument["holder_entity_id"] == "E1"
        assert instrument["timestamp_seconds"] == 1 and instrument["label"] == "crowbar"
        assert (items[0]["first_seen_seconds"], items[0]["last_seen_seconds"]) == (0, 2)
        assert "first_seen_seconds" not in instrument and "last_seen_seconds" not in items[2]

    def test_entities_stored_before_the_seen_span_fall_back_to_their_timestamp(self) -> None:
        (item,) = evidence_items({"entities": [{"entity_id": "E1", "timestamp_seconds": 5}]})
        assert (item["first_seen_seconds"], item["last_seen_seconds"]) == (5, 5)

    def test_items_without_an_id_are_dropped_and_timestamps_are_whole_seconds(self) -> None:
        items = evidence_items(
            {"entities": [{"type": "human"}, {"entity_id": "E2", "timestamp_seconds": 2.6}], "assets": None}
        )
        assert [i["item_id"] for i in items] == ["E2"]
        assert items[0]["timestamp_seconds"] == 3


class TestCropEvidenceService:
    """Test CropEvidenceService report processing."""

    @pytest.mark.asyncio
    async def test_process_incident_report_uploads_a_unique_crop_per_item(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[Detection(box=[200, 200, 600, 600], score=0.95, label="person")])
        store = InMemoryEvidenceStore()
        service = CropEvidenceService(detector=detector, store=store)

        results = await service.process_incident_report(
            video_ref=tiny_video_path,
            video_id="vabc",
            video_key="uploads/Burglary001.mp4",
            report=REPORT,
            batch_id="run-1",
        )

        assert [r["item_id"] for r in results] == ["E1", "I1", "A1"]
        for entry in results:
            assert entry["image"] == f"evidence/uploads/Burglary001.mp4/run-1/{entry['item_id']}.jpg"
            assert entry["image_gap"] is None
            assert len(entry["bounding_box"]) == 4
            assert await store.get_image(entry["image"]) is not None

    @pytest.mark.asyncio
    async def test_items_beyond_the_crop_call_cap_keep_a_cap_gap(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[Detection(box=[200, 200, 600, 600], score=0.95, label="x")])
        budget = CropCallBudget(2)
        service = CropEvidenceService(detector=detector, store=InMemoryEvidenceStore())
        results = await service.process_incident_report(
            video_ref=tiny_video_path, video_id="v", report=REPORT, detector=BudgetedDetector(detector, budget)
        )
        assert sum(1 for r in results if r["image"]) == 2
        assert [r["image_gap"] for r in results if not r["image"]] == [
            "crop-call cap reached: crop-call cap of 2 reached"
        ]
        assert budget.calls == 2 and budget.refused == 1

    @pytest.mark.asyncio
    async def test_each_run_gets_the_next_run_number_so_keys_are_never_overwritten(self, tiny_video_path: Path) -> None:
        service = CropEvidenceService(detector=FakeDetector(), store=InMemoryEvidenceStore())
        first = await service.process_incident_report(video_ref=tiny_video_path, video_id="v", report=REPORT)
        second = await service.process_incident_report(video_ref=tiny_video_path, video_id="v", report=REPORT)
        assert {e["image"] for e in first}.isdisjoint({e["image"] for e in second})
        assert {e["image"] for e in second} == {f"evidence/v/run-2/{e['item_id']}.jpg" for e in second}

    @pytest.mark.asyncio
    async def test_no_store_records_the_gap_for_every_item(self, tiny_video_path: Path) -> None:
        service = CropEvidenceService(detector=FakeDetector(), store=None)
        results = await service.process_incident_report(video_ref=tiny_video_path, video_id="v", report=REPORT)
        assert len(results) == 3
        assert all(r["image"] is None and r["bounding_box"] is None for r in results)
        assert all("store" in r["image_gap"] for r in results)

    @pytest.mark.asyncio
    async def test_unavailable_detector_records_the_gap_instead_of_dropping_items(self, tiny_video_path: Path) -> None:
        service = CropEvidenceService(detector=DefaultDetector(api_key=""), store=InMemoryEvidenceStore())
        assert not service.is_detector_available()
        results = await service.process_incident_report(video_ref=tiny_video_path, video_id="Vid1", report=REPORT)
        assert len(results) == 3
        assert all(r["image"] is None and "detector" in r["image_gap"] for r in results)

    @pytest.mark.asyncio
    async def test_upload_failure_is_recorded_per_item(self, tiny_video_path: Path) -> None:
        store = MagicMock()

        async def put_image(key: str, data: bytes, content_type: str = "image/jpeg") -> str:
            if key.endswith("I1.jpg"):
                raise RuntimeError("r2 down")
            return key

        store.put_image = put_image
        service = CropEvidenceService(detector=FakeDetector(), store=store)
        results = await service.process_incident_report(
            video_ref=tiny_video_path, video_id="v", report=REPORT, batch_id="b"
        )
        by_id = {r["item_id"]: r for r in results}
        assert by_id["E1"]["image"] == "evidence/v/b/E1.jpg"
        assert by_id["I1"]["image"] is None and "r2 down" in by_id["I1"]["image_gap"]
        assert by_id["A1"]["image"] == "evidence/v/b/A1.jpg"

    def test_global_service_get_and_set(self) -> None:
        orig = get_crop_evidence_service()
        custom = CropEvidenceService(detector=FakeDetector())
        set_crop_evidence_service(custom)
        assert get_crop_evidence_service() is custom
        set_crop_evidence_service(orig)
