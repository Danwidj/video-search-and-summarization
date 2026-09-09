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

"""The one-time Supabase seed importer is idempotent and keeps a stable FK.

Runs against the hermetic SQLite fixture - no live Supabase.
"""

from __future__ import annotations

from db import IncidentDB
from incident_report import INCIDENT_TYPES
from scripts.seed_data import INCIDENTS
from scripts.seed_supabase import seed


def _totals(db: IncidentDB) -> dict:
    reports = db.list_reports()
    return {
        "videos": len(db.list_videos()),
        "reports": len(reports),
        "entities": sum(len(db.list_incident_entities(r["id"])) for r in reports),
        "instruments": sum(len(db.list_incident_instruments(r["id"])) for r in reports),
        "assets": sum(len(db.list_incident_assets(r["id"])) for r in reports),
    }


def test_seed_loads_eight_incidents_with_evidence(incident_db: IncidentDB):
    counts = seed(incident_db)
    assert counts["videos"] == 8
    assert counts["reports"] == 8
    assert counts["entities"] == sum(len(i["entities"]) for i in INCIDENTS)
    assert counts["instruments"] == sum(len(i["instruments"]) for i in INCIDENTS)
    assert counts["assets"] == sum(len(i["assets"]) for i in INCIDENTS)
    assert _totals(incident_db) == {**counts}


def test_seed_is_idempotent(incident_db: IncidentDB):
    seed(incident_db)
    first = _totals(incident_db)
    fk_before = {r["incident_type"]: r["video_id"] for r in incident_db.list_reports()}

    seed(incident_db)
    assert _totals(incident_db) == first
    fk_after = {r["incident_type"]: r["video_id"] for r in incident_db.list_reports()}
    # Same incident -> same video row on every run (no recompute, no churn).
    assert fk_before == fk_after


def test_seed_rows_are_typed_for_the_footage(incident_db: IncidentDB):
    seed(incident_db)
    for report in incident_db.list_reports():
        assert report["incident_type"] in INCIDENT_TYPES
        assert report["model_version"] == "mock-seed-v1"
        video = incident_db.get_video(report["video_id"])
        assert video["r2_key"].startswith("normal_videos/")
        assert video["status"] == "analyzed"


def test_low_confidence_and_null_confidence_present(incident_db: IncidentDB):
    seed(incident_db)
    confidences = [r["confidence"] for r in incident_db.list_reports()]
    assert sum(1 for c in confidences if c is None) >= 2
    assert sum(1 for c in confidences if c is not None and c < 0.7) >= 2
