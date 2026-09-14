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

"""The Postgres seed importer populates the new schema from fixtures/data/*.csv.

Runs against the hermetic SQLite fixture - no live Postgres. It is idempotent
and keeps a stable video/incident identity (1 video = 1 incident) across runs.
"""

from __future__ import annotations

from db import IncidentDB
from incident_report import INCIDENT_TYPES
from scripts.seed_data import MODEL_RUN_ID, SYNTHETIC_INCIDENT_PREFIX, seed_rows
from scripts.seed_supabase import seed


def _totals(db: IncidentDB) -> dict:
    incidents = db.list_latest_incidents()
    return {
        "videos": len(db.list_videos()),
        "model_runs": len(db.list_model_runs()),
        "incidents": len(incidents),
        "entities": sum(len(db.list_incident_entities(r["incident_id"], MODEL_RUN_ID)) for r in incidents),
        "instruments": sum(len(db.list_incident_instruments(r["incident_id"], MODEL_RUN_ID)) for r in incidents),
        "assets": sum(len(db.list_incident_assets(r["incident_id"], MODEL_RUN_ID)) for r in incidents),
    }


def test_seed_loads_the_36_real_csv_incidents_with_evidence(incident_db: IncidentDB):
    counts = seed(incident_db)
    seed_data = seed_rows()
    assert counts["videos"] == 36
    assert counts["model_runs"] == 1
    assert counts["incidents"] == 36
    incident_ids = {incident["Incident_ID"] for incident in seed_data["Incident"]}
    assert not any(incident_id.startswith(SYNTHETIC_INCIDENT_PREFIX) for incident_id in incident_ids)
    # entities.csv/instruments.csv/assets.csv also carry SYN- rows (and one
    # known stray, RoadAccidents006/E2, with no incidents.csv row of its own -
    # fixtures/README.md gap #6); none of those have a surviving incident to
    # satisfy the FK, so they're skipped. seed_data() itself doesn't filter
    # the joined lists - only seed()'s incident_ids check does - so count
    # against the incident ids that actually made it through.
    assert counts["entities"] == sum(1 for e in seed_data["Entity"] if e["Incident_ID"] in incident_ids)
    assert counts["instruments"] == sum(1 for i in seed_data["Instrument"] if i["Incident_ID"] in incident_ids)
    assert counts["assets"] == sum(1 for a in seed_data["Asset"] if a["Incident_ID"] in incident_ids)
    assert _totals(incident_db) == {**counts}
    seeded_ids = {r["incident_id"] for r in incident_db.list_latest_incidents()}
    assert not any(incident_id.startswith(SYNTHETIC_INCIDENT_PREFIX) for incident_id in seeded_ids)


def test_seed_is_idempotent_and_keeps_the_video_incident_identity(incident_db: IncidentDB):
    seed(incident_db)
    first = _totals(incident_db)
    fk_before = {r["incident_id"]: r["video_filepath"] for r in incident_db.list_latest_incidents()}

    seed(incident_db)
    assert _totals(incident_db) == first
    fk_after = {r["incident_id"]: r["video_filepath"] for r in incident_db.list_latest_incidents()}
    # Same incident -> same video row on every run (no recompute, no churn).
    assert fk_before == fk_after


def test_seed_rows_are_typed_for_the_controlled_taxonomy(incident_db: IncidentDB):
    seed(incident_db)
    for row in incident_db.list_latest_incidents():
        assert row["type"] in INCIDENT_TYPES or row["type"] is None
        assert row["model_run_id"] == MODEL_RUN_ID
        assert row["video_filepath"].endswith(".mp4")
        # 1 video = 1 incident: the video id is the incident id itself.
        assert incident_db.get_video(row["incident_id"])["filepath"] == row["video_filepath"]


def test_confidence_is_null_for_all_real_ground_truth_incidents(incident_db: IncidentDB):
    # The real (non-SYN) incidents.csv rows never carry a Confidence_Score;
    # only the now-excluded SYN- placeholder rows did.
    seed(incident_db)
    confidences = [r["confidence_score"] for r in incident_db.list_latest_incidents()]
    assert confidences and all(c is None for c in confidences)


def test_reports_and_queries_stay_empty_reserved_shape(incident_db: IncidentDB):
    """Out of scope: no report-generation / query-submission workflow to seed."""
    seed(incident_db)
    assert incident_db.list_generated_reports() == []
    assert incident_db.list_queries() == []


def test_filepaths_are_real_r2_object_keys_not_the_old_placeholder(incident_db: IncidentDB):
    """Every Filepath is the exact anomaly/<category>/<filename> R2 key that
    filename names - never the media.example.invalid placeholder, and never a
    different clip substituted in from the same category."""
    seed_data = seed_rows()
    for incident in seed_data["Incident"]:
        assert not incident["Filepath"].startswith("http")
        assert incident["Filepath"] == f"anomaly/{incident['Filepath'].split('/')[1]}/{incident['Filename']}"
        assert incident["Filepath"].endswith(incident["Filename"])

    # Spot-check the verified category -> folder mapping (see PR description
    # for the full live-bucket cross-check across all 72 rows).
    by_id = {i["Incident_ID"]: i["Filepath"] for i in seed_data["Incident"]}
    assert by_id["Animal001"] == "anomaly/animal_attacks/Animal001_x264.mp4"
    assert by_id["Burglary001"] == "anomaly/burglary/Burglary001_x264.mp4"
    assert by_id["Explosion001"] == "anomaly/explosion/Explosion001_x264.mp4"
    assert by_id["RoadAccidents001"] == "anomaly/road_accidents/RoadAccidents001_x264.mp4"
    assert by_id["SYN-Fighting001"] == "anomaly/fighting/SYN-Fighting001_x264.mp4"
    # The 3 rows with a blank Type still resolve via the filename prefix.
    assert by_id["Burglary005"] == "anomaly/burglary/Burglary005_x264.mp4"
