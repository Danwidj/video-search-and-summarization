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

"""Unit tests for the MP4 header reader behind the agent's video-bounds rules."""

from __future__ import annotations

import math
import re
import struct

import httpx
import pytest

from vss_agents.utils.video_duration import MAX_MOOV_BYTES
from vss_agents.utils.video_duration import VideoDurationError
from vss_agents.utils.video_duration import mp4_duration_seconds
from vss_agents.utils.video_duration import url_duration_seconds
from vss_agents.utils.video_duration import valid_duration_seconds

VIDEO_URL = "https://r2.example/uploads/cam/clip.mp4?X-Amz-Signature=abc"


def box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def mvhd(seconds: float, *, timescale: int = 1000, version: int = 0) -> bytes:
    duration = round(seconds * timescale)
    if version == 1:
        body = bytes([1, 0, 0, 0]) + b"\0" * 16 + struct.pack(">IQ", timescale, duration)
    else:
        body = bytes([0, 0, 0, 0]) + b"\0" * 8 + struct.pack(">II", timescale, duration)
    return box(b"mvhd", body + b"\0" * 80)


def mp4(seconds: float = 12.5, *, moov_first: bool = False, version: int = 0, timescale: int = 1000) -> bytes:
    """A minimal MP4: ftyp, then mdat and moov (moov last by default, as many encoders write it)."""
    ftyp = box(b"ftyp", b"isom\0\0\0\0isom")
    mdat = box(b"mdat", b"\0" * 4096)
    moov = box(b"moov", box(b"trak", b"\0" * 32) + mvhd(seconds, timescale=timescale, version=version))
    return ftyp + (moov + mdat if moov_first else mdat + moov)


def range_server(data: bytes, seen: list[httpx.Request] | None = None):
    """An object store that honours single byte ranges like R2 does for a presigned GET."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers.get("range", ""))
        if match is None:
            return httpx.Response(200, content=data)
        start, end = int(match.group(1)), min(int(match.group(2)), len(data) - 1)
        chunk = data[start : end + 1]
        return httpx.Response(
            206, content=chunk, headers={"content-range": f"bytes {start}-{start + len(chunk) - 1}/{len(data)}"}
        )

    return handler


async def read_from(data: bytes, offset: int, length: int) -> bytes:
    return data[offset : offset + length]


class TestMp4DurationSeconds:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("moov_first", [False, True])
    @pytest.mark.parametrize("version", [0, 1])
    async def test_reads_mvhd_wherever_moov_is(self, moov_first, version):
        data = mp4(12.5, moov_first=moov_first, version=version)
        assert await mp4_duration_seconds(lambda o, n: read_from(data, o, n), len(data)) == 12.5

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("data", "reason"),
        [
            (b"", "no moov box"),
            (b"not an mp4 file at all, just text", "malformed top-level box"),
            (box(b"ftyp", b"isom") + box(b"mdat", b"\0" * 64), "no moov box"),
            (box(b"moov", box(b"trak", b"\0" * 16)), "no mvhd"),
            (box(b"moov", mvhd(0)), "no duration"),
        ],
    )
    async def test_unreadable_headers_raise_with_a_reason(self, data, reason):
        with pytest.raises(VideoDurationError, match=reason):
            await mp4_duration_seconds(lambda o, n: read_from(data, o, n), len(data))

    @pytest.mark.asyncio
    async def test_an_oversized_moov_is_not_read(self):
        data = struct.pack(">I4s", MAX_MOOV_BYTES + 9, b"moov")
        with pytest.raises(VideoDurationError, match="larger than"):
            await mp4_duration_seconds(lambda o, n: read_from(data, o, n), MAX_MOOV_BYTES + 9)


class TestUrlDurationSeconds:
    @pytest.mark.asyncio
    async def test_reads_the_length_with_ranged_gets_only(self):
        data = mp4(9.0)
        seen: list[httpx.Request] = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(range_server(data, seen))) as client:
            assert await url_duration_seconds(client, VIDEO_URL) == 9.0
        assert seen and all(r.method == "GET" and r.headers["range"].startswith("bytes=") for r in seen)
        # A size probe and three 16-byte box headers (ftyp, mdat, moov), then moov's body: never the mdat body.
        lengths = [int(end) - int(start) + 1 for start, end in (r.headers["range"][6:].split("-") for r in seen)]
        assert lengths[:4] == [8, 16, 16, 16]
        assert lengths[4] < 4096 and len(lengths) == 5

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "reason"),
        [
            (httpx.Response(200, content=mp4()), "HTTP 200"),
            (httpx.Response(403, text="SignatureDoesNotMatch"), "HTTP 403"),
            (httpx.Response(206, content=b"\0" * 8), "no Content-Range"),
        ],
    )
    async def test_an_unusable_answer_is_an_error_not_a_guess(self, response, reason):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: response)) as client:
            with pytest.raises(VideoDurationError, match=reason):
                await url_duration_seconds(client, VIDEO_URL)

    @pytest.mark.asyncio
    async def test_a_transport_failure_is_an_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(VideoDurationError, match="ConnectError"):
                await url_duration_seconds(client, VIDEO_URL)

    @pytest.mark.asyncio
    async def test_a_non_http_url_is_an_error(self):
        async with httpx.AsyncClient() as client:
            with pytest.raises(VideoDurationError, match="not an http"):
                await url_duration_seconds(client, "/srv/videos/clip.mp4")


@pytest.mark.parametrize(
    ("value", "valid"),
    [(12.5, True), (1, True), (0, False), (-3.0, False), (math.nan, False), (math.inf, False), (True, False)],
)
def test_valid_duration_seconds(value, valid):
    assert valid_duration_seconds(value) is valid
