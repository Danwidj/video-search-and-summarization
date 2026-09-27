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

"""Video length from an MP4 file's ``moov/mvhd`` header, read by byte ranges.

The contextual rule of validation policy core-scored-v1 (``contract.evaluate_policy``)
needs the real video length, which is runtime context rather than anything in the
schema. This reads it without ffmpeg: walk the top-level boxes (``ftyp``, ``mdat``,
``moov`` ... in any order - ``moov`` is often at the end) by reading only their
headers, then read ``moov`` and take ``mvhd`` duration / timescale. Anything
malformed or unreadable gives ``None`` (length unknown, so the rule is not applied);
it never guesses. Mirrors ``incident-console-v2/lib/video/mp4-duration.ts``.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Callable

# ``moov`` holds the sample tables; a few MB is typical, far more is not a header.
MAX_MOOV_BYTES = 64 * 1024 * 1024
MAX_TOP_LEVEL_BOXES = 1024

ReadRange = Callable[[int, int], bytes]
"""``read_range(offset, length)`` -> up to ``length`` bytes starting at ``offset``."""


def _box_header(data: bytes, file_offset: int, read_range: ReadRange, file_size: int) -> tuple[str, int, int] | None:
    """(type, header_size, box_size) of the box whose first bytes are ``data``."""
    if len(data) < 8:
        return None
    size, box_type = struct.unpack(">I4s", data[:8])
    header = 8
    if size == 1:
        if len(data) < 16:
            data = read_range(file_offset, 16)
            if len(data) < 16:
                return None
        size = struct.unpack(">Q", data[8:16])[0]
        header = 16
    elif size == 0:
        size = file_size - file_offset
    if size < header:
        return None
    return box_type.decode("latin-1"), header, size


def _mvhd_seconds(moov: bytes) -> float | None:
    """Duration from the ``mvhd`` box among ``moov``'s children."""
    offset = 0
    while offset + 8 <= len(moov):
        size, box_type = struct.unpack(">I4s", moov[offset:offset + 8])
        header = 8
        if size == 1:
            if offset + 16 > len(moov):
                return None
            size = struct.unpack(">Q", moov[offset + 8:offset + 16])[0]
            header = 16
        elif size == 0:
            size = len(moov) - offset
        if size < header or offset + size > len(moov):
            return None
        if box_type == b"mvhd":
            body = moov[offset + header:offset + size]
            if not body:
                return None
            version = body[0]
            if version == 1 and len(body) >= 4 + 16 + 12:
                timescale, duration = struct.unpack(">IQ", body[4 + 16:4 + 16 + 12])
            elif version == 0 and len(body) >= 4 + 8 + 8:
                timescale, duration = struct.unpack(">II", body[4 + 8:4 + 8 + 8])
            else:
                return None
            if timescale == 0 or duration in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                return None
            return duration / timescale
        offset += size
    return None


def mp4_duration_seconds(read_range: ReadRange, file_size: int) -> float | None:
    """Video length in seconds from an MP4's ``mvhd``, or ``None`` when it cannot be read."""
    try:
        offset = 0
        for _ in range(MAX_TOP_LEVEL_BOXES):
            if offset + 8 > file_size:
                return None
            parsed = _box_header(read_range(offset, 16), offset, read_range, file_size)
            if parsed is None:
                return None
            box_type, header, size = parsed
            if offset + size > file_size:
                return None
            if box_type == "moov":
                if size > MAX_MOOV_BYTES:
                    return None
                moov = read_range(offset + header, size - header)
                if len(moov) != size - header:
                    return None
                return _mvhd_seconds(moov)
            offset += size
        return None
    except (struct.error, OSError, ValueError):
        return None


def r2_video_duration_seconds(object_key: str) -> float | None:
    """Length of an R2 video object, read with ranged GETs; ``None`` if unknown."""
    import r2_videos  # lazy: needs R2 credentials

    try:
        client = r2_videos.client()
        bucket = os.environ["R2_BUCKET"]
        size = client.head_object(Bucket=bucket, Key=object_key)["ContentLength"]

        def read_range(offset: int, length: int) -> bytes:
            end = min(offset + length, size) - 1
            if end < offset:
                return b""
            return client.get_object(Bucket=bucket, Key=object_key, Range=f"bytes={offset}-{end}")["Body"].read()

        return mp4_duration_seconds(read_range, size)
    except Exception:  # noqa: BLE001 - any failure means "length unknown", never a guess
        return None
