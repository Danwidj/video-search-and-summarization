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

from db import IncidentDB, metadata


def test_init_schema_creates_all_four_tables(incident_db: IncidentDB):
    names = set(metadata.tables)
    assert {"videos", "incident_reports", "notifications", "severity_eval_log"} <= names
    # Idempotent - CREATE TABLE IF NOT EXISTS semantics.
    incident_db.init_schema()
    ok, detail = incident_db.healthcheck()
    assert ok, detail


def test_video_crud_roundtrip(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="clip1.mp4", r2_key="clip1.mp4")
    assert incident_db.get_video(vid)["status"] == "unanalyzed"

    incident_db.update_video_metadata(vid, location="Lobby", camera_source="CAM-1", edited_by="alice")
    row = incident_db.get_video(vid)
    assert row["location"] == "Lobby"
    assert row["metadata_edited_by"] == "alice"
    assert row["metadata_edited_at"] is not None

    incident_db.set_video_status(vid, "failed", error_message="boom")
    assert incident_db.get_video(vid)["status"] == "failed"

    assert incident_db.list_videos(status="failed")
    assert not incident_db.list_videos(status="analyzed")
    assert incident_db.list_videos(filename_like="clip1")

    incident_db.delete_video(vid)
    assert incident_db.get_video(vid) == {}


def test_report_insert_list_filter_and_edit(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="clip2.mp4")
    rid = incident_db.insert_report(
        video_id=vid,
        report={
            "incident_type": "robbery",
            "severity": 5,
            "confidence": 0.9,
            "incident_start": "0:10",
            "incident_end": "0:40",
            "incident_start_confirmed": True,
            "description": "Masked person at the counter.",
            "persons": [{"description": "masked adult", "actions": "grabbed items"}],
            "location": "Counter A",
        },
    )
    got = incident_db.get_report(rid)
    assert got["status"] == "unreviewed"
    assert got["persons"] == [{"description": "masked adult", "actions": "grabbed items"}]

    assert incident_db.list_reports(incident_type="robbery")
    assert not incident_db.list_reports(incident_type="vandalism")
    assert incident_db.list_reports(keyword="counter")
    assert incident_db.list_reports(status="unreviewed")

    incident_db.update_report(rid, fields={"severity": 3, "description": "Downgraded on review."}, edited_by="bob")
    got = incident_db.get_report(rid)
    assert got["severity"] == 3
    assert got["edited_by"] == "bob"
    assert got["edited_at"] is not None


def test_verify_report_raises_notification_above_threshold(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="clip3.mp4")
    high = incident_db.insert_report(video_id=vid, report={"incident_type": "assault/fighting", "severity": 4})
    low = incident_db.insert_report(video_id=vid, report={"incident_type": "trespassing", "severity": 2})

    out_high = incident_db.verify_report(high, verified_by="carol", notify_threshold=4)
    assert out_high == {"notified": True, "severity": 4}
    assert incident_db.get_report(high)["status"] == "verified"
    assert incident_db.get_report(high)["verified_by"] == "carol"

    out_low = incident_db.verify_report(low, verified_by="carol", notify_threshold=4)
    assert out_low["notified"] is False

    notes = incident_db.list_notifications()
    assert len(notes) == 1
    assert notes[0]["report_id"] == high
    assert notes[0]["acknowledged"] is False

    incident_db.acknowledge_notification(notes[0]["id"])
    assert not incident_db.list_notifications(only_unacknowledged=True)


def test_delete_report(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="clip4.mp4")
    rid = incident_db.insert_report(video_id=vid, report={"incident_type": "other", "severity": 1})
    incident_db.delete_report(rid)
    assert incident_db.get_report(rid) == {}


def test_severity_eval_log_crud(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="clip5.mp4")
    rid = incident_db.insert_report(video_id=vid, report={"incident_type": "other", "severity": 3})
    incident_db.insert_severity_eval(report_id=rid, ai_severity=3, human_severity=4, rater="dana")
    incident_db.insert_severity_eval(report_id=rid, ai_severity=3, human_severity=3, rater="erin")
    rows = incident_db.list_severity_evals()
    assert len(rows) == 2
    assert incident_db.severity_eval_counts()["total"] == 2
