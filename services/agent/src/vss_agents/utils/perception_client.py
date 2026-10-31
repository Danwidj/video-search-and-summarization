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

"""Client for the stock VSS perception stack that turns an uploaded clip into per-frame person boxes.

The chain is NvStreamer (file upload and RTSP replay) -> DeepStream (REST provisioning, detector plus tracker) ->
Kafka -> Logstash -> Elasticsearch -> video-analytics-api ``/frames``. The calls, payloads and failure modes are those
measured by the Phase 0 scout (see ``.docs/decisions.md`` in the incident profile):

* the NvStreamer ``streamId`` is taken from the upload response (a re-upload of a file name gets ``_1``, ``_2``);
* DeepStream ``stream/remove`` needs the same ``camera_url`` as ``stream/add``;
* ``/frames`` is newest first with at most 1000 frames a page, so the client pages backwards, and each object's
  1152-float embedding is dropped as the page is read (a page is about 10 MB with them);
* ``bbox`` is in source-video pixels, and ``confidence`` ``-0.1`` means tracked but not detected on that frame.

Base URLs come from ``NVSTREAMER_BASE_URL``, ``PERCEPTION_PROVISION_URL`` and ``VIDEO_ANALYTICS_API_URL``.
:class:`FakePerceptionClient` serves recorded ``/frames`` pages for unit tests.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import runtime_checkable

import httpx

logger = logging.getLogger(__name__)

NVSTREAMER_URL_ENV_VAR = "NVSTREAMER_BASE_URL"
PROVISION_URL_ENV_VAR = "PERCEPTION_PROVISION_URL"
VIDEO_ANALYTICS_URL_ENV_VAR = "VIDEO_ANALYTICS_API_URL"
DEFAULT_NVSTREAMER_URL = "http://localhost:31000"
DEFAULT_PROVISION_URL = "http://localhost:9000"
DEFAULT_VIDEO_ANALYTICS_URL = "http://localhost:8081"

FRAMES_PAGE_SIZE = 1000
# Frame timestamps are NTP times taken from NvStreamer's RTCP reports, not the VM clock (they ran 20 s to 11 min
# ahead), so the query window is wide instead of anchored on the VM clock.
FRAMES_FROM_TIMESTAMP = "2020-01-01T00:00:00.000Z"
FRAMES_TO_TIMESTAMP = "2100-01-01T00:00:00.000Z"
UPLOAD_TIMEOUT_SECONDS = 300.0
CALL_TIMEOUT_SECONDS = 30.0
FRAMES_TIMEOUT_SECONDS = 120.0


class PerceptionError(RuntimeError):
    """A perception-stack call failed or answered something unusable."""


@dataclass(frozen=True)
class FrameObject:
    """One tracked object on one frame; ``bbox`` is (left, top, right, bottom) in source-video pixels."""

    object_id: str
    type: str
    confidence: float  # detector score, or -0.1 on frames where the tracker alone placed the box
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class Frame:
    """One frame that has at least one object (frames without objects are never published)."""

    frame_id: int  # DeepStream frame number, counted from the first decoded frame of the RTSP session
    timestamp: str  # ISO 8601 with milliseconds
    objects: tuple[FrameObject, ...]


@dataclass(frozen=True)
class UploadedStream:
    stream_id: str  # NvStreamer's own id, taken from the upload response


def _env_url(name: str, default: str) -> str:
    return ((os.getenv(name) or "").strip() or default).rstrip("/")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_frame(raw: dict[str, Any]) -> Frame:
    """A :class:`Frame` from one ``/frames`` entry; the per-object embeddings are not read."""
    objects: list[FrameObject] = []
    for obj in raw.get("objects") or []:
        box = obj.get("bbox") or {}
        objects.append(
            FrameObject(
                object_id=str(obj.get("id")),
                type=str(obj.get("type") or ""),
                confidence=float(obj.get("confidence", 0.0)),
                bbox=(
                    float(box.get("leftX", 0.0)),
                    float(box.get("topY", 0.0)),
                    float(box.get("rightX", 0.0)),
                    float(box.get("bottomY", 0.0)),
                ),
            )
        )
    return Frame(frame_id=int(raw["id"]), timestamp=str(raw["timestamp"]), objects=tuple(objects))


_ONE_MS = timedelta(milliseconds=1)


def next_page_end(page: Sequence[Frame]) -> str:
    """``toTimestamp`` of the page after ``page``: the oldest timestamp of ``page`` minus 1 ms."""
    oldest = min(_parse_timestamp(frame.timestamp) for frame in page)
    return _format_timestamp(oldest - _ONE_MS)


def merge_pages(pages: Sequence[Sequence[Frame]]) -> list[Frame]:
    """All pages as one list, oldest first, without repeats.

    A frame repeated by a page boundary is dropped by its (id, timestamp) pair. The id alone is not enough: when
    DeepStream reconnects at the end of the file the counter restarts, so the replay pass reuses ids, and keeping
    the newest page's copy would drop the real pass.
    """
    seen: set[tuple[int, str]] = set()
    merged: list[Frame] = []
    for page in pages:
        for frame in page:
            key = (frame.frame_id, frame.timestamp)
            if key not in seen:
                seen.add(key)
                merged.append(frame)
    merged.sort(key=lambda frame: (_parse_timestamp(frame.timestamp), frame.frame_id))
    return merged


@runtime_checkable
class PerceptionClient(Protocol):
    """The calls a tracking run makes."""

    async def upload(self, path: Path, name: str, sensor_id: str) -> UploadedStream: ...

    async def stream_url(self, stream_id: str) -> str: ...

    async def delete_file(self, stream_id: str) -> None: ...

    async def add_stream(self, sensor_id: str, camera_url: str) -> None: ...

    async def remove_stream(self, sensor_id: str, camera_url: str) -> None: ...

    async def stream_count(self) -> int: ...

    async def latest_frame_id(self, sensor_id: str) -> int | None: ...

    async def frames(self, sensor_id: str) -> list[Frame]: ...


class HttpPerceptionClient:
    """The real stack over HTTP (NvStreamer, DeepStream REST, video-analytics-api)."""

    def __init__(
        self,
        nvstreamer_url: str | None = None,
        provision_url: str | None = None,
        analytics_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.nvstreamer_url = (nvstreamer_url or _env_url(NVSTREAMER_URL_ENV_VAR, DEFAULT_NVSTREAMER_URL)).rstrip("/")
        self.provision_url = (provision_url or _env_url(PROVISION_URL_ENV_VAR, DEFAULT_PROVISION_URL)).rstrip("/")
        self.analytics_url = (analytics_url or _env_url(VIDEO_ANALYTICS_URL_ENV_VAR, DEFAULT_VIDEO_ANALYTICS_URL)).rstrip(
            "/"
        )
        self._client = client

    async def _request(self, method: str, url: str, timeout: float = CALL_TIMEOUT_SECONDS, **kwargs: Any) -> Any:
        try:
            if self._client is not None:
                response = await self._client.request(method, url, timeout=timeout, **kwargs)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Only the path is named: the message must not carry a URL with credentials or a query.
            raise PerceptionError(f"{method} {httpx.URL(url).path}: {type(exc).__name__}: {exc}") from exc
        return response

    async def upload(self, path: Path, name: str, sensor_id: str) -> UploadedStream:
        metadata = json.dumps({"streamName": sensor_id, "sensorId": sensor_id})
        with path.open("rb") as media:
            response = await self._request(
                "POST",
                f"{self.nvstreamer_url}/api/v1/storage/file",
                timeout=UPLOAD_TIMEOUT_SECONDS,
                files={"metadata": (None, metadata, "application/json"), "mediaFile": (name, media, "video/mp4")},
            )
        stream_id = str(response.json().get("streamId") or "")
        if not stream_id:
            raise PerceptionError("NvStreamer upload answered without a streamId")
        return UploadedStream(stream_id=stream_id)

    async def stream_url(self, stream_id: str) -> str:
        response = await self._request("GET", f"{self.nvstreamer_url}/api/v1/sensor/streams")
        for group in response.json():
            for entries in group.values():
                for entry in entries:
                    if entry.get("streamId") == stream_id and entry.get("url"):
                        return str(entry["url"])
        raise PerceptionError(f"NvStreamer lists no RTSP url for stream {stream_id}")

    async def delete_file(self, stream_id: str) -> None:
        await self._request("DELETE", f"{self.nvstreamer_url}/api/v1/sensor/{stream_id}")

    @staticmethod
    def _sensor_body(sensor_id: str, camera_url: str, change: str) -> dict[str, Any]:
        now = _format_timestamp(datetime.now(UTC))
        value: dict[str, Any] = {
            "camera_id": sensor_id,
            "camera_name": sensor_id,
            "camera_url": camera_url,
            "change": change,
            "metadata": {},
        }
        if change == "camera_add":
            value["creation_time"] = now
            value["metadata"] = {"resolution": "1920x1080", "codec": "h264", "framerate": 30}
        return {"key": "sensor", "value": value, "headers": {"source": "vst", "created_at": now}}

    async def add_stream(self, sensor_id: str, camera_url: str) -> None:
        await self._request(
            "POST",
            f"{self.provision_url}/api/v1/stream/add",
            json=self._sensor_body(sensor_id, camera_url, "camera_add"),
            headers={"x-stream-id": sensor_id},
        )

    async def remove_stream(self, sensor_id: str, camera_url: str) -> None:
        await self._request(
            "POST",
            f"{self.provision_url}/api/v1/stream/remove",
            json=self._sensor_body(sensor_id, camera_url, "camera_remove"),
        )

    async def stream_count(self) -> int:
        response = await self._request("GET", f"{self.provision_url}/api/v1/stream/get-stream-info")
        return int(response.json().get("stream-count") or 0)

    async def metrics(self) -> dict[str, Any]:
        """DeepStream's ``/metrics`` (``stream-stats`` per stream); a liveness signal, since ``/ready`` stays YES."""
        response = await self._request("GET", f"{self.provision_url}/api/v1/metrics")
        body = response.json()
        return body if isinstance(body, dict) else {}

    async def _page(self, sensor_id: str, to_timestamp: str, size: int) -> list[Frame]:
        response = await self._request(
            "GET",
            f"{self.analytics_url}/frames",
            timeout=FRAMES_TIMEOUT_SECONDS,
            params={
                "sensorId": sensor_id,
                "fromTimestamp": FRAMES_FROM_TIMESTAMP,
                "toTimestamp": to_timestamp,
                "maxResultSize": size,
            },
        )
        return [parse_frame(raw) for raw in response.json().get("frames") or []]

    async def latest_frame_id(self, sensor_id: str) -> int | None:
        page = await self._page(sensor_id, FRAMES_TO_TIMESTAMP, 1)
        return page[0].frame_id if page else None

    async def frames(self, sensor_id: str) -> list[Frame]:
        pages: list[list[Frame]] = []
        to_timestamp = FRAMES_TO_TIMESTAMP
        while True:
            page = await self._page(sensor_id, to_timestamp, FRAMES_PAGE_SIZE)
            if page:
                pages.append(page)
            if len(page) < FRAMES_PAGE_SIZE:
                return merge_pages(pages)
            to_timestamp = next_page_end(page)


class FakePerceptionClient:
    """In-memory stack for unit tests, serving recorded ``/frames`` pages (newest first, as the API does).

    ``pages`` are raw ``/frames`` response bodies (``{"frames": [...]}``) or lists of frames, newest page first.
    ``page_size`` makes :meth:`frames` page like the real API; the default is the real one.
    """

    def __init__(
        self,
        pages: Sequence[Any] = (),
        *,
        page_size: int = FRAMES_PAGE_SIZE,
        fail: dict[str, Exception] | None = None,
    ) -> None:
        self.pages = [list(page["frames"]) if isinstance(page, dict) else list(page) for page in pages]
        self.page_size = page_size
        self.fail = fail or {}
        self.calls: list[str] = []
        self.uploaded: dict[str, Path] = {}
        self.streams: set[str] = set()
        self.added: dict[str, str] = {}
        self.removed: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.page_requests: list[str] = []

    def _record(self, call: str) -> None:
        self.calls.append(call)
        if call in self.fail:
            raise self.fail[call]

    async def upload(self, path: Path, name: str, sensor_id: str) -> UploadedStream:  # noqa: ARG002
        self._record("upload")
        stream_id = Path(name).stem
        self.uploaded[stream_id] = path
        self.streams.add(stream_id)
        return UploadedStream(stream_id=stream_id)

    async def stream_url(self, stream_id: str) -> str:
        self._record("stream_url")
        return f"rtsp://fake/{stream_id}"

    async def delete_file(self, stream_id: str) -> None:
        self.calls.append("delete_file")
        self.deleted.append(stream_id)
        self.streams.discard(stream_id)
        if "delete_file" in self.fail:
            raise self.fail["delete_file"]

    async def add_stream(self, sensor_id: str, camera_url: str) -> None:
        self._record("add_stream")
        self.added[sensor_id] = camera_url

    async def remove_stream(self, sensor_id: str, camera_url: str) -> None:
        self.calls.append("remove_stream")
        self.removed.append((sensor_id, camera_url))
        self.added.pop(sensor_id, None)
        if "remove_stream" in self.fail:
            raise self.fail["remove_stream"]

    async def stream_count(self) -> int:
        self._record("stream_count")
        return len(self.added)

    async def _all(self) -> list[Frame]:
        # Serve through the same paging rule as HttpPerceptionClient so the rule is exercised.
        pages: list[list[Frame]] = []
        to_timestamp = FRAMES_TO_TIMESTAMP
        everything = sorted(
            (parse_frame(raw) for page in self.pages for raw in page),
            key=lambda frame: _parse_timestamp(frame.timestamp),
            reverse=True,
        )
        while True:
            self.page_requests.append(to_timestamp)
            end = _parse_timestamp(to_timestamp)
            page = [frame for frame in everything if _parse_timestamp(frame.timestamp) <= end][: self.page_size]
            if page:
                pages.append(page)
            if len(page) < self.page_size:
                return merge_pages(pages)
            to_timestamp = next_page_end(page)

    async def latest_frame_id(self, sensor_id: str) -> int | None:  # noqa: ARG002
        self._record("latest_frame_id")
        frames = await self._all()
        return frames[-1].frame_id if frames else None

    async def frames(self, sensor_id: str) -> list[Frame]:  # noqa: ARG002
        self._record("frames")
        return await self._all()
