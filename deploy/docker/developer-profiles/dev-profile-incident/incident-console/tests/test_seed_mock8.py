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

"""The captain's 8-video demo set seed importer.

Runs against the hermetic SQLite fixture - no live Postgres/R2. It is
idempotent and lives under its own model_run_id (MOCK8) so it never collides
with the 72-row ground-truth seed (scripts/seed_supabase.py, model_run_id
MR-SEED).
"""

from __future__ import annotations

from db import IncidentDB
from scripts.seed_mock8 import INCIDENTS, MODEL_RUN_ID, seed
from scripts.seed_supabase import MODEL_RUN_ID as GT_MODEL_RUN_ID
from scripts.seed_supabase import seed as seed_ground_truth


def _totals(db: IncidentDB) -> dict:
    incidents = db.list_incidents(model_run_id=MODEL_RUN_ID)
    return {
        "videos": len(db.list_videos()),
        "model_runs": len(db.list_model_runs()),
        "incidents": len(incidents),
        "entities": sum(len(db.list_incident_entities(r["incident_id"], MODEL_RUN_ID)) for r in incidents),
        "instruments": sum(len(db.list_incident_instruments(r["incident_id"], MODEL_RUN_ID)) for r in incidents),
        "assets": sum(len(db.list_incident_assets(r["incident_id"], MODEL_RUN_ID)) for r in incidents),
    }


def test_seed_loads_the_8_mock_incidents_with_evidence(incident_db: IncidentDB):
    counts = seed(incident_db)
    assert counts["videos"] == 8
    assert counts["model_runs"] == 1
    assert counts["incidents"] == 8
    assert counts["entities"] == sum(len(i["entities"]) for i in INCIDENTS)
    assert counts["instruments"] == sum(len(i["instruments"]) for i in INCIDENTS)
    assert counts["assets"] == sum(len(i["assets"]) for i in INCIDENTS)
    assert _totals(incident_db) == {**counts}


def test_seed_is_idempotent(incident_db: IncidentDB):
    seed(incident_db)
    first = _totals(incident_db)
    seed(incident_db)
    assert _totals(incident_db) == first


def test_every_video_points_at_a_normal_videos_key_matching_its_clip(incident_db: IncidentDB):
    seed(incident_db)
    for incident in INCIDENTS:
        video = incident_db.get_video(incident["incident_id"])
        assert video["filepath"] == f"normal_videos/{incident['filename']}"


def test_each_incident_links_a_distinct_clip(incident_db: IncidentDB):
    seed(incident_db)
    filepaths = [incident_db.get_video(i["incident_id"])["filepath"] for i in INCIDENTS]
    assert len(filepaths) == len(set(filepaths))


def test_mock8_never_collides_with_the_ground_truth_seed(incident_db: IncidentDB):
    """The two seeds are independent: running both leaves both fully intact."""
    gt_counts = seed_ground_truth(incident_db)
    mock_counts = seed(incident_db)
    assert MODEL_RUN_ID != GT_MODEL_RUN_ID
    assert len(incident_db.list_incidents(model_run_id=GT_MODEL_RUN_ID)) == gt_counts["incidents"]
    assert len(incident_db.list_incidents(model_run_id=MODEL_RUN_ID)) == mock_counts["incidents"]
    incident_ids = {i["incident_id"] for i in INCIDENTS}
    ground_truth_ids = {r["incident_id"] for r in incident_db.list_incidents(model_run_id=GT_MODEL_RUN_ID)}
    assert incident_ids.isdisjoint(ground_truth_ids)
