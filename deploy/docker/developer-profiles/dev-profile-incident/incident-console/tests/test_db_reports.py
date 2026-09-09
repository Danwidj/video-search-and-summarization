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

"""DB-backed Report Review view model: edits and status changes persist."""

from __future__ import annotations

import pytest

from db_reports import DBReports
from scripts.seed_supabase import seed


@pytest.fixture
def seeded(incident_db):
    seed(incident_db)
    return incident_db


def _first_report_id(db):
    return sorted(r["id"] for r in db.list_reports())[0]


def test_list_and_get_expose_the_local_reports_shape(seeded):
    view = DBReports(seeded).list_reports()
    assert len(view) == 8
    row = view[0]
    for key in (
        "id",
        "filename",
        "incident_type",
        "incident_start",
        "incident_end",
        "duration",
        "severity",
        "confidence",
        "status",
        "r2_key",
        "location",
        "verified_by",
        "verified_at",
        "edited_by",
        "edited_at",
    ):
        assert key in row
    assert row["filename"].endswith(".mp4")


def test_field_edit_round_trips_through_a_fresh_handle(seeded):
    rid = _first_report_id(seeded)
    DBReports(seeded).update_report(rid, fields={"description": "reviewer correction", "severity": 5})
    # A brand-new handle == a page refresh: the change must still be there.
    reloaded = DBReports(seeded).get_report(rid)
    assert reloaded["description"] == "reviewer correction"
    assert reloaded["severity"] == 5


def test_timestamps_are_normalised_to_hhmmss(seeded):
    rid = _first_report_id(seeded)
    DBReports(seeded).update_report(rid, fields={"incident_start": "1:05", "incident_end": "90"})
    reloaded = DBReports(seeded).get_report(rid)
    assert reloaded["incident_start"] == "00:01:05"
    assert reloaded["incident_end"] == "00:01:30"


def test_review_status_change_persists(seeded):
    rid = _first_report_id(seeded)
    DBReports(seeded).set_review_status(rid, status="under review", reviewed_by="alice")
    assert DBReports(seeded).get_report(rid)["status"] == "under review"
    DBReports(seeded).set_review_status(rid, status="verified", reviewed_by="alice")
    assert DBReports(seeded).get_report(rid)["status"] == "verified"


def test_review_status_change_round_trips_reviewer_attribution(seeded):
    """Regression: ``_to_view`` dropped the attribution columns, so a saved
    "Reviewed by" name was written to Postgres but never read back into the view
    model - it looked unsaved after navigating away and back."""
    rid = _first_report_id(seeded)
    DBReports(seeded).set_review_status(rid, status="verified", reviewed_by="dana")
    # A brand-new handle == a page refresh / in-app re-open.
    reloaded = DBReports(seeded).get_report(rid)
    assert reloaded["status"] == "verified"
    assert reloaded["verified_by"] == "dana"
    assert reloaded["edited_by"] == "dana"
    assert reloaded["verified_at"] is not None
    assert reloaded["edited_at"] is not None


def test_non_verified_status_carries_editor_but_no_verifier(seeded):
    rid = _first_report_id(seeded)
    DBReports(seeded).set_review_status(rid, status="under review", reviewed_by="erin")
    reloaded = DBReports(seeded).get_report(rid)
    assert reloaded["edited_by"] == "erin"
    assert reloaded["verified_by"] is None


def test_field_edit_round_trips_edited_by_attribution(seeded):
    rid = _first_report_id(seeded)
    DBReports(seeded).update_report(rid, fields={"description": "reviewer correction"}, edited_by="fran")
    reloaded = DBReports(seeded).get_report(rid)
    assert reloaded["description"] == "reviewer correction"
    assert reloaded["edited_by"] == "fran"
    assert reloaded["edited_at"] is not None


def test_relinking_video_persists_a_stable_fk(seeded):
    rid = _first_report_id(seeded)
    before = DBReports(seeded).get_report(rid)["r2_key"]
    target = "anomaly/burglary/Burglary001_x264.mp4"
    assert target != before
    DBReports(seeded).link_video(rid, target, edited_by="reviewer")
    after = DBReports(seeded).get_report(rid)
    assert after["r2_key"] == target
    # Re-open again: still the same clip (fixed relationship, not recomputed).
    assert DBReports(seeded).get_report(rid)["r2_key"] == target


def test_get_video_seeks_from_incident_start(seeded):
    rid = _first_report_id(seeded)
    view = DBReports(seeded).get_report(rid)
    video = DBReports(seeded).get_video(rid)
    # r2 is stubbed unconfigured in tests, so Filepath falls back to the key,
    # but the row the auto-seek needs (key + incident_start seconds) is present.
    assert video["R2_Key"] == view["r2_key"]
    assert view["incident_start"] == "00:00:04"
