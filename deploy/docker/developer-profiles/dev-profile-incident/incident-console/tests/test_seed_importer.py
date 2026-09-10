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
from scripts.seed_data import MODEL_RUN_ID, seed_rows
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


def test_seed_loads_the_72_csv_incidents_with_evidence(incident_db: IncidentDB):
    counts = seed(incident_db)
    seed_data = seed_rows()
    assert counts["videos"] == 72
    assert counts["model_runs"] == 1
    assert counts["incidents"] == 72
    # entities.csv carries one known stray row (RoadAccidents006/E2) with no
    # incidents.csv row of its own (fixtures/README.md gap #6); it has no
    # incident to satisfy the entities->incidents FK and is skipped.
    assert counts["entities"] == len(seed_data["Entity"]) - 1
    assert counts["instruments"] == len(seed_data["Instrument"])
    assert counts["assets"] == len(seed_data["Asset"])
    assert _totals(incident_db) == {**counts}


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


def test_low_confidence_and_null_confidence_present(incident_db: IncidentDB):
    seed(incident_db)
    confidences = [r["confidence_score"] for r in incident_db.list_latest_incidents()]
    assert sum(1 for c in confidences if c is None) >= 10
    assert sum(1 for c in confidences if c is not None and c < 0.7) >= 5


def test_reports_and_queries_stay_empty_reserved_shape(incident_db: IncidentDB):
    """Out of scope: no report-generation / query-submission workflow to seed."""
    seed(incident_db)
    assert incident_db.list_generated_reports() == []
    assert incident_db.list_queries() == []
