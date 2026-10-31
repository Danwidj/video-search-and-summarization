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

"""Unit tests for the perception client: the NvStreamer and DeepStream calls and the /frames paging rule."""

import json
from pathlib import Path

import httpx
import pytest

from vss_agents.utils.perception_client import FakePerceptionClient
from vss_agents.utils.perception_client import Frame
from vss_agents.utils.perception_client import HttpPerceptionClient
from vss_agents.utils.perception_client import PerceptionError
from vss_agents.utils.perception_client import merge_pages
from vss_agents.utils.perception_client import next_page_end
from vss_agents.utils.perception_client import parse_frame

FIXTURES = Path(__file__).parent / "fixtures" / "perception"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _raw_frame(frame_id: int, timestamp: str, **object_fields) -> dict:
    obj = {
        "id": "3",
        "type": "Person",
        "confidence": 0.9,
        "bbox": {"leftX": 1.0, "topY": 2.0, "rightX": 3.0, "bottomY": 4.0, "embeddings": [0.1] * 5},
        "embedding": {"vector": [0.5] * 1152},
        **object_fields,
    }
    return {"id": str(frame_id), "timestamp": timestamp, "sensorId": "s", "objects": [obj]}


class TestParsing:
    def test_a_frame_keeps_the_box_in_pixels_and_drops_the_embeddings(self):
        frame = parse_frame(_raw_frame(7, "2026-10-31T08:00:00.000Z"))
        assert frame.frame_id == 7
        assert frame.objects[0].bbox == (1.0, 2.0, 3.0, 4.0)  # left, top, right, bottom
        assert frame.objects[0].confidence == 0.9
        assert not any("embedding" in name for name in vars(frame.objects[0]))

    def test_the_next_page_ends_one_millisecond_before_the_oldest_frame(self):
        page = [Frame(2, "2026-10-31T08:00:01.500Z", ()), Frame(1, "2026-10-31T08:00:01.000Z", ())]
        assert next_page_end(page) == "2026-10-31T08:00:00.999Z"

    def test_a_repeated_frame_is_dropped_but_the_replay_pass_that_reuses_its_id_is_kept(self):
        first = Frame(5, "2026-10-31T08:00:00.000Z", ())
        replay = Frame(5, "2026-10-31T08:01:00.000Z", ())
        merged = merge_pages([[replay, first], [first]])
        assert merged == [first, replay]  # oldest first


class TestFakeClientPaging:
    @pytest.mark.asyncio
    async def test_two_recorded_pages_are_read_newest_first_and_merged(self):
        pages = [_load("frames_4569_page1.json"), _load("frames_4569_page2.json")]
        client = FakePerceptionClient(pages)
        frames = await client.frames("scout-4569")
        assert len(frames) == 1427
        assert [f.timestamp for f in frames] == sorted(f.timestamp for f in frames)  # oldest first
        assert len(client.page_requests) == 2  # 1000 frames, then the 427 before them
        oldest_of_first_page = sorted(frames, key=lambda f: f.timestamp)[427]
        assert client.page_requests[1] < oldest_of_first_page.timestamp

    @pytest.mark.asyncio
    async def test_a_page_boundary_that_repeats_frames_does_not_duplicate_them(self):
        raw = [_raw_frame(i, f"2026-10-31T08:00:0{i}.000Z") for i in range(6)]
        client = FakePerceptionClient([raw, raw[3:]], page_size=2)
        frames = await client.frames("s")
        assert [f.frame_id for f in frames] == [0, 1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_the_latest_frame_id_is_the_newest_frame(self):
        client = FakePerceptionClient(
            [[_raw_frame(1, "2026-10-31T08:00:00.000Z"), _raw_frame(9, "2026-10-31T08:00:01.000Z")]]
        )
        assert await client.latest_frame_id("s") == 9
        assert await FakePerceptionClient().latest_frame_id("s") is None


def _http(handler) -> HttpPerceptionClient:
    return HttpPerceptionClient(
        "http://nvstreamer:31000",
        "http://deepstream:9000",
        "http://analytics:8081",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestHttpClient:
    @pytest.mark.asyncio
    async def test_upload_sends_the_metadata_json_and_takes_the_stream_id_from_the_response(self, tmp_path: Path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"video")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"id": "run_1", "streamId": "run_1", "sensorId": "run"})

        uploaded = await _http(handler).upload(clip, "run.mp4", "run")
        assert uploaded.stream_id == "run_1"  # not the file stem: NvStreamer appends _1 on a repeated name
        body = seen[0].content.decode(errors="replace")
        assert seen[0].url.path == "/api/v1/storage/file"
        assert '{"streamName": "run", "sensorId": "run"}' in body and "mediaFile" in body

    @pytest.mark.asyncio
    async def test_the_rtsp_url_is_the_one_listed_for_the_stream_id(self):
        listing = [
            {"a": [{"streamId": "a", "url": "rtsp://h:1/a"}]},
            {"b": [{"streamId": "b", "url": "rtsp://h:2/b"}]},
        ]
        client = _http(lambda _: httpx.Response(200, json=listing))
        assert await client.stream_url("b") == "rtsp://h:2/b"
        with pytest.raises(PerceptionError):
            await client.stream_url("missing")

    @pytest.mark.asyncio
    async def test_add_and_remove_carry_the_same_camera_url(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"reason": "OK"})

        client = _http(handler)
        await client.add_stream("run", "rtsp://h:1/a")
        await client.remove_stream("run", "rtsp://h:1/a")
        add, remove = (json.loads(r.content) for r in seen)
        assert [r.url.path for r in seen] == ["/api/v1/stream/add", "/api/v1/stream/remove"]
        assert add["value"]["camera_id"] == "run" and add["value"]["change"] == "camera_add"
        assert add["value"]["camera_url"] == remove["value"]["camera_url"] == "rtsp://h:1/a"
        assert remove["value"]["change"] == "camera_remove"
        assert seen[0].headers["x-stream-id"] == "run"

    @pytest.mark.asyncio
    async def test_delete_uses_the_sensor_route_and_stream_count_reads_the_stream_info(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"stream-count": 2})

        client = _http(handler)
        await client.delete_file("a_1")
        assert await client.stream_count() == 2
        assert (seen[0].method, seen[0].url.path) == ("DELETE", "/api/v1/sensor/a_1")

    @pytest.mark.asyncio
    async def test_frames_page_backwards_with_the_documented_query(self):
        newest = [_raw_frame(i, f"2026-10-31T08:00:{i:02d}.000Z") for i in (3, 2)]
        oldest = [_raw_frame(1, "2026-10-31T08:00:01.000Z")]
        queries: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            queries.append(dict(request.url.params))
            return httpx.Response(200, json={"frames": newest if len(queries) == 1 else oldest})

        client = _http(handler)
        client_page = 2
        from vss_agents.utils import perception_client

        original = perception_client.FRAMES_PAGE_SIZE
        perception_client.FRAMES_PAGE_SIZE = client_page
        try:
            frames = await client.frames("run")
        finally:
            perception_client.FRAMES_PAGE_SIZE = original
        assert [f.frame_id for f in frames] == [1, 2, 3]
        assert queries[0]["sensorId"] == "run" and queries[0]["maxResultSize"] == "2"
        assert queries[1]["toTimestamp"] == "2026-10-31T08:00:01.999Z"

    @pytest.mark.asyncio
    async def test_a_http_failure_is_a_perception_error_that_names_the_path_only(self):
        client = _http(lambda _: httpx.Response(503))
        with pytest.raises(PerceptionError) as caught:
            await client.stream_count()
        assert "/api/v1/stream/get-stream-info" in str(caught.value)
