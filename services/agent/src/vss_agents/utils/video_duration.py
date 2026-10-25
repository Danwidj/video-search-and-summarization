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

"""Video length from an MP4's ``moov/mvhd`` header, read from a URL by HTTP byte ranges.

The contextual rules of validation policy core-scored-v1 (``WINDOW_BEYOND_VIDEO``,
``TIMELINE_BEYOND_VIDEO``) need the real video length, which is runtime context rather
than anything in the schema. This reads it without ffmpeg or a full download: walk the
top-level boxes (``ftyp``, ``mdat``, ``moov`` ... in any order) by reading only their
headers, then read ``moov`` and take ``mvhd`` duration / timescale. Mirrors the profile's
``eval/video_duration.py`` and ``incident-console-v2/src/lib/video/mp4-duration.ts``.

It never guesses: anything malformed or unreadable is :class:`VideoDurationError` with a
reason the caller records, so an unchecked video is visible rather than silent.
"""

from collections.abc import Awaitable
from collections.abc import Callable
import math
import re
import struct

import httpx

# ``moov`` holds the sample tables; a few MB is typical, far more is not a header.
MAX_MOOV_BYTES = 64 * 1024 * 1024
MAX_TOP_LEVEL_BOXES = 1024
_CONTENT_RANGE = re.compile(r"^bytes \d+-\d+/(\d+)$")

ReadRange = Callable[[int, int], Awaitable[bytes]]
"""``await read_range(offset, length)`` -> up to ``length`` bytes starting at ``offset``."""


class VideoDurationError(Exception):
    """The video length could not be read; the message says why."""


def valid_duration_seconds(value: object) -> bool:
    """Whether ``value`` is a usable video length: a finite number of seconds above zero."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _mvhd_seconds(moov: bytes) -> float:
    """Duration from the ``mvhd`` box among ``moov``'s children."""
    offset = 0
    while offset + 8 <= len(moov):
        size, box_type = struct.unpack(">I4s", moov[offset : offset + 8])
        header = 8
        if size == 1:
            if offset + 16 > len(moov):
                raise VideoDurationError("truncated 64-bit box size inside moov")
            size = struct.unpack(">Q", moov[offset + 8 : offset + 16])[0]
            header = 16
        elif size == 0:
            size = len(moov) - offset
        if size < header or offset + size > len(moov):
            raise VideoDurationError("malformed box inside moov")
        if box_type == b"mvhd":
            body = moov[offset + header : offset + size]
            version = body[0] if body else None
            if version == 1 and len(body) >= 4 + 16 + 12:
                timescale, duration = struct.unpack(">IQ", body[4 + 16 : 4 + 16 + 12])
            elif version == 0 and len(body) >= 4 + 8 + 8:
                timescale, duration = struct.unpack(">II", body[4 + 8 : 4 + 8 + 8])
            else:
                raise VideoDurationError("unsupported or truncated mvhd box")
            if timescale == 0 or duration in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                raise VideoDurationError("mvhd declares no duration")
            return float(duration / timescale)
        offset += size
    raise VideoDurationError("moov has no mvhd box")


async def mp4_duration_seconds(read_range: ReadRange, file_size: int) -> float:
    """Video length in seconds from an MP4's ``mvhd``; raises :class:`VideoDurationError` when unreadable."""
    offset = 0
    for _ in range(MAX_TOP_LEVEL_BOXES):
        if offset + 8 > file_size:
            raise VideoDurationError("no moov box before the end of the file (not an MP4?)")
        head = await read_range(offset, 16)
        if len(head) < 8:
            raise VideoDurationError("truncated box header")
        size, box_type = struct.unpack(">I4s", head[:8])
        header = 8
        if size == 1:
            if len(head) < 16:
                raise VideoDurationError("truncated 64-bit box size")
            size = struct.unpack(">Q", head[8:16])[0]
            header = 16
        elif size == 0:
            size = file_size - offset
        if size < header or offset + size > file_size:
            raise VideoDurationError("malformed top-level box (not an MP4?)")
        if box_type == b"moov":
            if size > MAX_MOOV_BYTES:
                raise VideoDurationError(f"moov box is larger than {MAX_MOOV_BYTES} bytes")
            moov = await read_range(offset + header, size - header)
            if len(moov) != size - header:
                raise VideoDurationError("truncated moov box")
            return _mvhd_seconds(moov)
        offset += size
    raise VideoDurationError(f"no moov box in the first {MAX_TOP_LEVEL_BOXES} top-level boxes")


async def url_duration_seconds(client: httpx.AsyncClient, url: str) -> float:
    """Length of the MP4 at ``url`` (a signed R2 URL), read with ranged GETs.

    A presigned GET URL does not allow ``HEAD``, so the file size comes from the
    ``Content-Range`` of the first ranged read. A server that ignores ``Range`` is an
    error rather than a full download. ``client`` must not carry model credentials:
    the request goes to the object store, not the model endpoint.
    """
    if not url.lower().startswith(("http://", "https://")):
        raise VideoDurationError("the video URL is not an http(s) URL")
    # The file size, learnt from the first ranged read's Content-Range.
    known_size: list[int] = []

    async def read_range(offset: int, length: int) -> bytes:
        end = offset + length - 1 if not known_size else min(offset + length, known_size[0]) - 1
        if end < offset:
            return b""
        async with client.stream("GET", url, headers={"Range": f"bytes={offset}-{end}"}) as response:
            if response.status_code != 206:
                raise VideoDurationError(f"a ranged read of the video returned HTTP {response.status_code}")
            match = _CONTENT_RANGE.match(response.headers.get("content-range", ""))
            if match is None:
                raise VideoDurationError("a ranged read of the video gave no Content-Range size")
            if not known_size:
                known_size.append(int(match.group(1)))
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > length:
                    raise VideoDurationError("a ranged read of the video returned more bytes than asked for")
            return bytes(data)

    try:
        await read_range(0, 8)
        seconds = await mp4_duration_seconds(read_range, known_size[0])
    except httpx.HTTPError as exc:
        raise VideoDurationError(f"reading the video header failed: {type(exc).__name__}: {exc}") from exc
    if not valid_duration_seconds(seconds):
        raise VideoDurationError(f"the MP4 header gives an unusable length ({seconds!r})")
    return seconds
