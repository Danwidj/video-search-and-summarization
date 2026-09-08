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

from __future__ import annotations

import pytest

from incident_report import (
    agreement_rate,
    build_insights,
    canned_incident_report,
    extract_message_content,
    group_notifications,
    incident_report_from_dict,
    parse_incident_report,
    playback_start_seconds,
    seconds_to_timestamp,
    severity_disagreement,
    severity_triggers_notification,
    timestamp_to_seconds,
    to_completion_payload,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0:45", 45),
        ("1:30", 90),
        ("1:02:03", 3723),
        ("90", 90),
        ("", 0),
        ("garbage", 0),
        (None, 0),
        (12.7, 12),
        ("-5", 0),
    ],
)
def test_timestamp_to_seconds_fallback(value, expected):
    assert timestamp_to_seconds(value) == expected


def test_seconds_to_timestamp_roundtrip():
    assert seconds_to_timestamp(45) == "0:45"
    assert seconds_to_timestamp(90) == "1:30"
    assert seconds_to_timestamp(3723) == "1:02:03"
    assert seconds_to_timestamp(None) == "0:00"


def test_playback_start_defaults_to_zero_when_unconfirmed():
    assert playback_start_seconds({"incident_start": "1:00", "incident_start_confirmed": False}) == 0
    assert playback_start_seconds({"incident_start": "1:00", "incident_start_confirmed": True}) == 60


def test_severity_thresholds():
    assert severity_triggers_notification(4, 4) is True
    assert severity_triggers_notification(3, 4) is False
    assert severity_triggers_notification(None, 4) is False
    assert severity_disagreement(5, 3, 1) is True
    assert severity_disagreement(4, 3, 1) is False
    assert severity_disagreement("x", 3, 1) is False


def test_agreement_rate():
    rows = [
        {"ai_severity": 3, "human_severity": 3},
        {"ai_severity": 3, "human_severity": 4},
        {"ai_severity": 2, "human_severity": 2},
        {"ai_severity": None, "human_severity": 2},
    ]
    assert agreement_rate(rows) == pytest.approx(2 / 3)
    assert agreement_rate([]) == 0.0


def test_group_notifications_windows_and_preserves_all():
    rows = [
        {"id": 1, "created_at_epoch": 0},
        {"id": 2, "created_at_epoch": 100},
        {"id": 3, "created_at_epoch": 500},
        {"id": 4, "created_at_epoch": None},
    ]
    groups = group_notifications(rows, window_seconds=300)
    flat = [r["id"] for g in groups for r in g]
    assert sorted(flat) == [1, 2, 3, 4]  # nothing dropped
    # ids 1 & 2 fall in one window; id 3 opens a new one; the timestamp-less
    # id 4 is isolated into its own group.
    id_groups = [sorted(r["id"] for r in g) for g in groups]
    assert [1, 2] in id_groups
    assert [3] in id_groups
    assert [4] in id_groups


def test_build_insights_templates():
    reports = [
        {"incident_type": "robbery", "location": "Counter A", "severity": 5},
        {"incident_type": "robbery", "location": "Counter A", "severity": 2},
        {"incident_type": "trespassing", "location": "Lot", "severity": 1},
    ]
    lines = build_insights(reports)
    assert any("robbery" in line for line in lines)
    assert any("Counter A" in line for line in lines)
    assert build_insights([]) == ["No verified incident reports match the current filters."]


def test_incident_report_from_dict_clamps_and_normalizes():
    report = incident_report_from_dict(
        {
            "incident_type": "TRAFFIC",
            "severity": 9,
            "confidence": 87.0,
            "incident_start": 65,
            "incident_end": "2:00",
            "persons": [{"description": "p1", "actions": "ran"}, "p2"],
        }
    )
    assert report.incident_type == "traffic"
    assert report.severity == 5
    assert report.confidence == pytest.approx(0.87)
    assert report.incident_start == "1:05"
    assert len(report.persons) == 2
    # Unknown type falls back to "other".
    assert incident_report_from_dict({"incident_type": "meteor"}).incident_type == "other"


def test_parse_incident_report_from_fenced_json_and_bare_and_plain():
    fenced = 'noise\n```json\n{"incident_type": "traffic", "severity": 3}\n```\ntail'
    assert parse_incident_report(fenced).incident_type == "traffic"

    bare = 'lead {"incident_type": "equipment", "severity": 2} trail'
    assert parse_incident_report(bare).incident_type == "equipment"

    plain = parse_incident_report("no structure here")
    assert plain.incident_type == "other"
    assert plain.description == "no structure here"


def test_completion_payload_roundtrips_through_parser():
    report = canned_incident_report("worker on the ladder top rung")
    payload = to_completion_payload(report)
    content = extract_message_content(payload)
    parsed = parse_incident_report(content)
    assert parsed.incident_type == "warehouse safety"
    assert parsed.severity == 4
