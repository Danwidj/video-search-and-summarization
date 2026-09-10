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

import datetime as dt

from db import IncidentDB, metadata


def test_init_schema_creates_the_full_table_set(incident_db: IncidentDB):
    names = set(metadata.tables)
    assert {
        "videos",
        "queries",
        "model_runs",
        "reports",
        "incidents",
        "entities",
        "instruments",
        "assets",
        "gt_incidents",
        "gt_entities",
        "gt_instruments",
        "gt_assets",
        "entity_matches",
        "instrument_matches",
        "asset_matches",
        "review_status",
        "notifications",
        "severity_eval_log",
    } <= names
    # Idempotent - CREATE TABLE IF NOT EXISTS semantics.
    incident_db.init_schema()
    ok, detail = incident_db.healthcheck()
    assert ok, detail


def test_video_crud_roundtrip(incident_db: IncidentDB):
    incident_db.upsert_video("Clip001", filepath="normal_videos/clip1.mp4", duration=42)
    row = incident_db.get_video("Clip001")
    assert row["filepath"] == "normal_videos/clip1.mp4"
    assert row["duration"] == 42

    incident_db.upsert_video("Clip001", filepath="normal_videos/clip1-renamed.mp4", duration=50)
    assert incident_db.get_video("Clip001")["filepath"] == "normal_videos/clip1-renamed.mp4"
    assert len(incident_db.list_videos()) == 1

    incident_db.update_video("Clip001", filepath="normal_videos/relinked.mp4")
    assert incident_db.get_video("Clip001")["filepath"] == "normal_videos/relinked.mp4"

    incident_db.delete_video("Clip001")
    assert incident_db.get_video("Clip001") == {}


def test_model_run_and_query_crud(incident_db: IncidentDB):
    incident_db.insert_model_run("MR-1", model_name="incident-vlm", model_version="1.0", prompt_version="p1")
    run = incident_db.get_model_run("MR-1")
    assert run["model_name"] == "incident-vlm"
    assert run["prompt_version"] == "p1"
    assert len(incident_db.list_model_runs()) == 1

    incident_db.insert_query("Q1", query_text="show me burglaries near the loading dock")
    query = incident_db.get_query("Q1")
    assert query["query_text"] == "show me burglaries near the loading dock"
    assert len(incident_db.list_queries()) == 1


def _seed_one_incident(db: IncidentDB, *, incident_id="Burglary001", model_run_id="MR-1", severity=4):
    db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4", duration=120)
    db.insert_model_run(model_run_id, model_name="incident-vlm", prompt_version="p1")
    db.insert_incident(
        incident_id,
        model_run_id,
        fields={
            "type": "burglary",
            "start_timestamp": "00:00:08",
            "end_timestamp": "00:01:57",
            "duration": 109,
            "description": "a person forces open a side door.",
            "severity_level": severity,
            "confidence_score": 0.9,
        },
    )
    return incident_id, model_run_id


def test_incident_insert_list_filter_and_update(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_one_incident(incident_db)

    got = incident_db.get_incident(incident_id, model_run_id)
    assert got["type"] == "burglary"
    assert got["severity_level"] == 4

    assert incident_db.list_incidents(model_run_id=model_run_id)
    assert not incident_db.list_incidents(model_run_id="MR-OTHER")

    incident_db.update_incident(incident_id, model_run_id, fields={"severity_level": 2, "description": "downgraded"})
    got = incident_db.get_incident(incident_id, model_run_id)
    assert got["severity_level"] == 2
    assert got["description"] == "downgraded"


def test_insert_incident_is_idempotent_and_resets_review_status(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_one_incident(incident_db)
    incident_db.set_review_status(incident_id, model_run_id, status="verified", reviewed_by="alice", notify_threshold=5)

    # Re-inserting (as a seed re-import would) resets the review workflow too.
    incident_db.insert_incident(
        incident_id, model_run_id, fields={"type": "burglary", "severity_level": 4, "description": "re-seeded"}
    )
    assert incident_db.get_review_status(incident_id, model_run_id)["status"] == "unreviewed"
    assert len(incident_db.list_incidents(model_run_id=model_run_id)) == 1


def test_latest_incident_view_joins_video_and_model_run(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_one_incident(incident_db)
    row = incident_db.get_latest_incident(incident_id)
    assert row["video_filepath"] == f"normal_videos/{incident_id}.mp4"
    assert row["model_run_id"] == model_run_id
    assert row["status"] == "unreviewed"

    rows = incident_db.list_latest_incidents(type_="burglary")
    assert len(rows) == 1
    assert not incident_db.list_latest_incidents(type_="explosion")

    keyword_rows = incident_db.list_latest_incidents(keyword="side door")
    assert len(keyword_rows) == 1


def test_latest_incident_prefers_the_most_recent_model_run(incident_db: IncidentDB):
    incident_id = "Explosion001"
    incident_db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4")
    incident_db.insert_model_run("MR-OLD", model_name="m", prompt_version="p", run_datetime=dt.datetime(2026, 1, 1))
    incident_db.insert_model_run("MR-NEW", model_name="m", prompt_version="p", run_datetime=dt.datetime(2026, 6, 1))
    incident_db.insert_incident(incident_id, "MR-OLD", fields={"type": "explosion", "severity_level": 1})
    incident_db.insert_incident(incident_id, "MR-NEW", fields={"type": "explosion", "severity_level": 5})

    latest = incident_db.get_latest_incident(incident_id)
    assert latest["model_run_id"] == "MR-NEW"
    assert latest["severity_level"] == 5


def test_review_status_notifies_on_verify_above_threshold(incident_db: IncidentDB):
    high_id, model_run_id = _seed_one_incident(incident_db, incident_id="High001", severity=4)
    low_id, _ = _seed_one_incident(incident_db, incident_id="Low001", model_run_id=model_run_id, severity=2)

    out_high = incident_db.set_review_status(
        high_id, model_run_id, status="verified", reviewed_by="carol", notify_threshold=4
    )
    assert out_high == {"notified": True, "severity": 4}
    assert incident_db.get_review_status(high_id, model_run_id)["status"] == "verified"
    assert incident_db.get_review_status(high_id, model_run_id)["verified_by"] == "carol"

    out_low = incident_db.set_review_status(
        low_id, model_run_id, status="verified", reviewed_by="carol", notify_threshold=4
    )
    assert out_low["notified"] is False

    notes = incident_db.list_notifications()
    assert len(notes) == 1
    assert notes[0]["incident_id"] == high_id
    assert notes[0]["acknowledged"] is False

    incident_db.acknowledge_notification(notes[0]["id"])
    assert not incident_db.list_notifications(only_unacknowledged=True)

    # Repeating the same status is a no-op, not a second notification.
    incident_db.set_review_status(high_id, model_run_id, status="verified", reviewed_by="carol", notify_threshold=4)
    assert len(incident_db.list_notifications()) == 1


def test_delete_incident(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_one_incident(incident_db)
    incident_db.delete_incident(incident_id, model_run_id)
    assert incident_db.get_incident(incident_id, model_run_id) == {}


def test_severity_eval_log_crud(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_one_incident(incident_db)
    incident_db.insert_severity_eval(
        incident_id=incident_id, model_run_id=model_run_id, ai_severity=3, human_severity=4, rater="dana"
    )
    incident_db.insert_severity_eval(
        incident_id=incident_id, model_run_id=model_run_id, ai_severity=3, human_severity=3, rater="erin"
    )
    rows = incident_db.list_severity_evals()
    assert len(rows) == 2
    assert incident_db.severity_eval_counts()["total"] == 2
