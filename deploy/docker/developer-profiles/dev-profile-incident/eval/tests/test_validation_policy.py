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

"""core-scored-v1 (contract.evaluate_policy) and the MP4 length reader (video_duration)."""

from __future__ import annotations

import json
import struct

import pytest

import contract
from video_duration import mp4_duration_seconds

FIXTURES = contract.CONTRACTS_DIR / "fixtures"


def _report(**incident) -> dict:
    report = json.loads((FIXTURES / "valid" / "minimal-report.json").read_text())
    report["incident"].update(incident)
    return report


def test_timeline_only_failure_keeps_the_prediction_unaltered():
    report = _report(start_timestamp=16, end_timestamp=22)
    report["timeline"] = [
        {"start_seconds": 0, "end_seconds": 11, "description": "Two animals run along the path."},
        {"start_seconds": 16, "end_seconds": 22, "description": "The child is attacked."},
    ]
    content = json.dumps(report)
    result = contract.evaluate_policy(content, 22.83)
    assert result["full_contract_ok"] is False
    assert result["core_ok"] is True
    assert [v["code"] for v in result["enrichment"]] == ["TIMELINE_START_OUTSIDE_WINDOW"]
    # Nothing is repaired, clipped or removed: only the derived duration is added.
    derived = result["report"]
    assert derived["timeline"] == report["timeline"]
    assert {**derived, "incident": {k: v for k, v in derived["incident"].items() if k != "duration"}} == report
    assert derived["incident"]["duration"] == 6
    with pytest.raises(contract.ContractError):
        contract.parse_report(content)


def test_core_failure_gives_no_report():
    report = _report(start_timestamp=29, end_timestamp=36)
    report["timeline"] = [{"start_seconds": 29, "end_seconds": None, "description": "x"}]
    result = contract.evaluate_policy(json.dumps(report), 12.54)
    assert result["core_ok"] is False and result["report"] is None
    assert {v["code"] for v in result["core"]} == {"WINDOW_BEYOND_VIDEO"}
    assert {v["code"] for v in result["enrichment"]} == {"TIMELINE_BEYOND_VIDEO"}


def test_video_rule_never_changes_full_contract_validity():
    report = _report(start_timestamp=29, end_timestamp=36)
    report["timeline"] = [{"start_seconds": 30, "end_seconds": None, "description": "x"}]
    result = contract.evaluate_policy(json.dumps(report), 12.54)
    assert result["full_contract_ok"] is True
    assert result["core_ok"] is False


def test_unknown_length_is_not_checked():
    result = contract.evaluate_policy(json.dumps(_report(start_timestamp=0, end_timestamp=10_000)), None)
    assert result["core_ok"] is True
    assert result["video_bounds_checked"] is False


@pytest.mark.parametrize(
    ("duration", "accepted", "rejected"),
    [(12.54, 13, 14), (22.0, 22, 23), (22.83, 23, 24)],
)
def test_whole_second_boundary(duration, accepted, rejected):
    assert contract.timestamp_within_video(accepted, duration)
    assert not contract.timestamp_within_video(rejected, duration)
    assert contract.timestamp_within_video(0, duration)
    assert not contract.timestamp_within_video(-1, duration)


def test_scopes():
    assert contract.violation_scope("TIMELINE_NOT_CHRONOLOGICAL") == "enrichment"
    assert contract.violation_scope("TIMELINE_BEYOND_VIDEO") == "enrichment"
    for code in ("WINDOW_END_BEFORE_START", "WINDOW_BEYOND_VIDEO", "ID_NOT_SEQUENTIAL_ENTITY",
                 "INSTRUMENT_HOLDER_UNKNOWN", "SCHEMA_VIOLATION", "INVALID_JSON", "EMPTY_CONTENT"):
        assert contract.violation_scope(code) == "core"


def test_cross_field_errors_keep_their_v2_messages():
    report = _report(start_timestamp=3, end_timestamp=7)
    report["timeline"] = [{"start_seconds": 0, "end_seconds": None, "description": "x"}]
    assert contract.cross_field_errors(report) == ["timeline[0].start_seconds 0 is outside [3, 7]"]


# --- MP4 length --------------------------------------------------------------------


def _box(box_type: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), box_type) + body


def _mvhd(timescale: int, duration: int, version: int = 0) -> bytes:
    if version == 1:
        body = bytes([1, 0, 0, 0]) + bytes(16) + struct.pack(">IQ", timescale, duration) + bytes(80)
    else:
        body = bytes([0, 0, 0, 0]) + bytes(8) + struct.pack(">II", timescale, duration) + bytes(80)
    return _box(b"mvhd", body)


def _reader(data: bytes, calls: list | None = None):
    def read_range(offset: int, length: int) -> bytes:
        if calls is not None:
            calls.append((offset, length))
        return data[offset:offset + length]
    return read_range


def test_mp4_duration_with_moov_after_mdat_reads_only_headers_and_moov():
    moov = _box(b"moov", _box(b"trak", bytes(24)) + _mvhd(1000, 12539))
    data = _box(b"ftyp", b"isom" + bytes(12)) + _box(b"mdat", bytes(500_000)) + moov
    calls: list = []
    assert mp4_duration_seconds(_reader(data, calls), len(data)) == pytest.approx(12.539)
    assert sum(length for _, length in calls) < 2_000  # the 500 kB mdat is skipped, never read


def test_mp4_duration_version_1_and_largesize_box():
    mdat = struct.pack(">I4sQ", 1, b"mdat", 16 + 100) + bytes(100)
    data = _box(b"ftyp", bytes(8)) + mdat + _box(b"moov", _mvhd(600, 13_700, version=1))
    assert mp4_duration_seconds(_reader(data), len(data)) == pytest.approx(13_700 / 600)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not an mp4 file at all",
        _box(b"ftyp", bytes(8)) + _box(b"mdat", bytes(64)),  # no moov
        _box(b"moov", _box(b"trak", bytes(8))),  # no mvhd
        _box(b"moov", _mvhd(0, 100)),  # zero timescale
        struct.pack(">I4s", 4000, b"mdat") + bytes(10),  # box runs past the file
    ],
)
def test_mp4_duration_unknown_when_unreadable(data):
    assert mp4_duration_seconds(_reader(data), len(data)) is None
