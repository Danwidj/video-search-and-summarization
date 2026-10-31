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

"""Unit tests for set-of-marks prompting: numbering, drawing, the marked copy, and parsing the marks back."""

import json
from pathlib import Path
import shutil

import cv2
import numpy as np
import pytest

from vss_agents.utils import chunk_captions
from vss_agents.utils import set_of_marks
from vss_agents.utils.perception_client import FakePerceptionClient
from vss_agents.utils.set_of_marks import Mark
from vss_agents.utils.set_of_marks import MarkedClip
from vss_agents.utils.set_of_marks import apply_marks
from vss_agents.utils.set_of_marks import boxes_at
from vss_agents.utils.set_of_marks import cleanup_marks
from vss_agents.utils.set_of_marks import marks_context
from vss_agents.utils.set_of_marks import number_tracks
from vss_agents.utils.set_of_marks import parse_mark
from vss_agents.utils.set_of_marks import prepare_marks
from vss_agents.utils.set_of_marks import render_marked_clip
from vss_agents.utils.set_of_marks import som_enabled
from vss_agents.utils.track_evidence import ClipInfo
from vss_agents.utils.track_evidence import Sample
from vss_agents.utils.track_evidence import Track
from vss_agents.utils.track_evidence import TrackingOutcome
from vss_agents.utils.track_evidence import TrackingRequest
from vss_agents.utils.track_evidence import TrackingSettings
from vss_agents.utils.track_evidence import run_tracking

from .test_chunk_captions import FakeR2

VIDEO_URL = "https://r2.example/uploads/cam/clip.mp4?X-Amz-Signature=abc"
FIXTURES = Path(__file__).parent / "fixtures" / "perception"
CLIP_8206 = ClipInfo(width=854, height=480, fps=29.97, frames=2823, duration_seconds=94.2)


def _track(track_id: str, start: float, end: float, box=(200, 200, 600, 600)) -> Track:
    steps = round((end - start) / 0.2)
    return Track(track_id, [Sample(round(start + i * 0.2, 3), box, 0.9) for i in range(steps + 1)])


def _report(*labels: tuple[str, int]) -> dict:
    return {
        "entities": [
            {"entity_id": f"E{i}", "type": "human", "label": label, "timestamp_seconds": seconds}
            for i, (label, seconds) in enumerate(labels, start=1)
        ]
    }


class TestFlagAndNumbering:
    @pytest.mark.parametrize(("value", "on"), [(None, False), ("", False), ("0", False), ("1", True), ("true", True)])
    def test_the_flag_is_off_unless_truthy(self, monkeypatch, value, on):
        if value is None:
            monkeypatch.delenv("INCIDENT_SOM_ENABLED", raising=False)
        else:
            monkeypatch.setenv("INCIDENT_SOM_ENABLED", value)
        assert som_enabled() is on

    def test_tracks_are_numbered_from_one_in_order_of_first_appearance(self):
        late, early, empty = _track("900", 5.0, 6.0), _track("31", 1.0, 2.0), Track("7")
        marks = number_tracks([late, empty, early])
        assert [(m.number, m.track.track_id) for m in marks] == [(1, "31"), (2, "900")]

    def test_a_box_is_drawn_only_near_a_sample_of_its_track(self):
        marks = number_tracks([_track("a", 1.0, 2.0), Track("b", [Sample(1.0, (1, 2, 3, 4), 0.9)])])
        assert [n for n, _ in boxes_at(marks, 1.1)] == [1, 2]
        assert [n for n, _ in boxes_at(marks, 1.9)] == [1]
        assert boxes_at(marks, 2.5) == [] and boxes_at(marks, 0.5) == []

    def test_the_context_names_every_mark_and_its_span(self):
        text = marks_context(number_tracks([_track("a", 1.0, 2.0), _track("b", 3.0, 4.4)]))
        assert text.startswith(set_of_marks.MARKS_PREAMBLE)
        assert "[1] on screen 1.0s to 2.0s" in text and "[2] on screen 3.0s to 4.4s" in text


class TestParseAndApply:
    @pytest.mark.parametrize(
        ("label", "number", "stripped"),
        [
            ("person in dark hoodie [2]", 2, "person in dark hoodie"),
            ("person [ #3 ]", 3, "person"),
            ("[1] man in red [4]", 4, "man in red"),
            ("person in dark hoodie", None, "person in dark hoodie"),
            ("person (2)", None, "person (2)"),
        ],
    )
    def test_parse_reads_the_last_bracketed_number_and_strips_all(self, label, number, stripped):
        assert parse_mark(label) == (number, stripped)

    def test_a_valid_number_matches_its_track_and_the_label_is_stripped(self):
        marks = number_tracks([_track("31", 1.0, 3.0), _track("900", 4.0, 8.0)])
        report = _report(("person in red [2]", 6), ("person in blue [1]", 2))
        matched, invalid = apply_marks(report, marks)
        assert {k: t.track_id for k, t in matched.items()} == {"E1": "900", "E2": "31"} and invalid == 0
        assert [e["label"] for e in report["entities"]] == ["person in red", "person in blue"]

    def test_a_missing_or_invalid_number_is_not_matched_but_still_stripped(self):
        marks = number_tracks([_track("31", 1.0, 3.0), _track("900", 4.0, 8.0)])
        report = _report(
            ("person without a mark", 2),
            ("person with an unknown mark [7]", 2),
            ("person whose mark is elsewhere at that second [2]", 2),
            ("person with a taken mark [1]", 2),
            ("first holder of the mark [1]", 2),
        )
        # E5 comes after E4 in the report, so E4 takes mark 1 and E5's claim is invalid.
        matched, invalid = apply_marks(report, marks)
        assert list(matched) == ["E4"] and invalid == 3
        assert all("[" not in e["label"] for e in report["entities"])

    def test_a_number_on_an_entity_without_a_second_is_invalid(self):
        report = {"entities": [{"entity_id": "E1", "label": "person [1]"}]}
        assert apply_marks(report, number_tracks([_track("a", 0.0, 1.0)])) == ({}, 1)
        assert report["entities"][0]["label"] == "person"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
class TestRender:
    def test_the_marked_copy_keeps_size_and_frames_and_draws_only_where_the_track_is(self, tmp_path: Path):
        source, target = tmp_path / "clip.mp4", tmp_path / "marked.mp4"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (160, 120))
        for _ in range(20):
            writer.write(np.full((120, 160, 3), 128, dtype=np.uint8))
        writer.release()
        marks = number_tracks([_track("5", 0.0, 0.4, box=(250, 250, 750, 750))])

        render_marked_clip(source, target, marks, shutil.which("ffmpeg") or "ffmpeg")

        capture = cv2.VideoCapture(str(target))
        frames = []
        ok, frame = capture.read()
        while ok:
            frames.append(frame)
            ok, frame = capture.read()
        capture.release()
        assert len(frames) == 20 and frames[0].shape == (120, 160, 3)
        edge = (60, 40)  # the box's left edge, halfway down
        blue, _, red = (int(c) for c in frames[0][edge])
        assert red > 180 and blue < 110  # mark 1 is red
        assert abs(int(frames[15][edge][2]) - 128) < 20  # past the track's end, the frame is untouched


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.5)


def _perception_request(client: FakePerceptionClient) -> TrackingRequest:
    time = FakeTime()

    async def probe(path: Path) -> ClipInfo:
        return CLIP_8206

    return TrackingRequest(
        sensor_id="incident-abc-run1",
        runner=run_tracking,
        options={
            "client": client,
            "settings": TrackingSettings(),
            "probe": probe,
            "sleep": time.sleep,
            "clock": time.clock,
        },
    )


def _first_pass() -> list[dict]:
    frames = sorted(json.loads((FIXTURES / "frames_8206.json").read_text())["frames"], key=lambda f: f["timestamp"])
    cut: list[dict] = []
    for frame in frames:
        if cut and int(frame["id"]) < int(cut[-1]["id"]):
            break
        cut.append(frame)
    return cut


class TestPrepare:
    @pytest.fixture(autouse=True)
    def _no_download(self, monkeypatch):
        async def fake_download(video_url: str, target: Path) -> None:
            assert video_url == VIDEO_URL
            target.write_bytes(b"source")

        def fake_render(source: Path, target: Path, marks: list[Mark], ffmpeg: str) -> None:
            assert source.read_bytes() == b"source"
            self.rendered = [m.number for m in marks]
            target.write_bytes(b"marked")

        self.rendered: list[int] = []
        monkeypatch.setattr(chunk_captions, "download_video", fake_download)
        monkeypatch.setattr(chunk_captions, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
        monkeypatch.setattr(set_of_marks, "render_marked_clip", fake_render)

    @staticmethod
    def _store(r2: FakeR2) -> chunk_captions.ScratchStore:
        return chunk_captions.ScratchStore(bucket="bucket", client=r2)

    @pytest.mark.asyncio
    async def test_the_fake_stack_tracks_the_downloaded_file_and_the_copy_goes_to_scratch(self):
        client, r2 = FakePerceptionClient([_first_pass()]), FakeR2()
        marked = await prepare_marks(
            VIDEO_URL,
            video_key="uploads/a.mp4",
            run_id="run1",
            tracking=_perception_request(client),
            store=self._store(r2),
        )
        assert marked.skipped is None and marked.outcome is not None and marked.outcome.tracks
        assert client.uploaded["incident-abc-run1"].name == "source.mp4"  # the local download, not the URL
        assert self.rendered == list(range(1, len(marked.outcome.tracks) + 1))
        assert marked.prefix == "scratch/analyze/uploads/a.mp4/run1-marks/"
        assert r2.objects == {"scratch/analyze/uploads/a.mp4/run1-marks/marked.mp4": b"marked"}
        assert marked.url == "https://signed.example/scratch/analyze/uploads/a.mp4/run1-marks/marked.mp4?sig=1"
        assert marked.telemetry()["rendered"] is True

        await cleanup_marks(marked)
        assert r2.objects == {} and r2.deleted == ["scratch/analyze/uploads/a.mp4/run1-marks/marked.mp4"]

    @pytest.mark.asyncio
    async def test_no_frames_from_the_stack_renders_nothing(self):
        r2 = FakeR2()
        marked = await prepare_marks(
            VIDEO_URL,
            video_key="k",
            run_id="r",
            tracking=_perception_request(FakePerceptionClient([])),
            store=self._store(r2),
        )
        assert (
            marked.url is None and marked.skipped == "no tracks to mark (tracking skipped: no frames from perception)"
        )
        assert marked.outcome is not None and r2.objects == {} and self.rendered == []

    @pytest.mark.asyncio
    async def test_a_render_failure_keeps_the_tracks_and_uploads_nothing(self, monkeypatch):
        def broken(*_: object) -> None:
            raise RuntimeError("ffmpeg failed encoding the marked copy: boom")

        monkeypatch.setattr(set_of_marks, "render_marked_clip", broken)
        r2 = FakeR2()
        outcome = TrackingOutcome(tracks=[_track("1", 0.0, 1.0)])

        async def runner(*_: object, **__: object) -> TrackingOutcome:
            return outcome

        marked = await prepare_marks(
            VIDEO_URL,
            video_key="k",
            run_id="r",
            tracking=TrackingRequest(sensor_id="s", runner=runner),
            store=self._store(r2),
        )
        assert marked.url is None and "rendering the marked copy failed" in (marked.skipped or "")
        assert marked.outcome is outcome and r2.objects == {}

    @pytest.mark.asyncio
    async def test_an_upload_failure_leaves_no_url_and_cleanup_still_deletes(self):
        class FailingR2(FakeR2):
            def put_object(self, **kwargs: object) -> None:
                super().put_object(**kwargs)  # type: ignore[arg-type]
                raise RuntimeError("r2 down after the write")

        r2 = FailingR2()

        async def runner(*_: object, **__: object) -> TrackingOutcome:
            return TrackingOutcome(tracks=[_track("1", 0.0, 1.0)])

        marked = await prepare_marks(
            VIDEO_URL,
            video_key="k",
            run_id="r",
            tracking=TrackingRequest(sensor_id="s", runner=runner),
            store=self._store(r2),
        )
        assert marked.url is None and marked.skipped == "uploading the marked copy failed (RuntimeError)"
        await cleanup_marks(marked)
        assert r2.objects == {}

    @pytest.mark.asyncio
    async def test_a_failed_download_is_soft_and_never_names_the_url(self, monkeypatch):
        async def broken(video_url: str, target: Path) -> None:
            raise RuntimeError(f"cannot fetch {video_url}")

        monkeypatch.setattr(chunk_captions, "download_video", broken)
        marked = await prepare_marks(
            VIDEO_URL,
            video_key="k",
            run_id="r",
            tracking=TrackingRequest(sensor_id="s"),
            store=self._store(FakeR2()),
        )
        assert marked.url is None and marked.outcome is None
        assert marked.skipped == "the clip could not be downloaded (RuntimeError)"

    @pytest.mark.asyncio
    async def test_cleanup_never_raises(self):
        class Broken:
            async def delete_prefix(self, prefix: str) -> int:
                raise RuntimeError("r2 down")

        await cleanup_marks(None)
        await cleanup_marks(MarkedClip(prefix="p/", store=Broken()))  # type: ignore[arg-type]
