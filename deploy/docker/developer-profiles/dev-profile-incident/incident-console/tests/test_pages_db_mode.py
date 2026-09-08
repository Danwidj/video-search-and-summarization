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

"""Report Review and Dashboard render from the database when a DSN is configured.

The database is the hermetic SQLite fixture; R2 stays stubbed unconfigured.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from scripts.seed_supabase import seed


@pytest.fixture
def db_pages(incident_db, monkeypatch):
    seed(incident_db)
    monkeypatch.setattr("config.incident_db_dsn", lambda: str(incident_db.engine.url))
    monkeypatch.setattr("db.is_configured", lambda: True)
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    return incident_db


def test_report_review_lists_the_eight_from_the_db(db_pages):
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    assert not app.exception
    assert len([b for b in app.button if b.label == "View and Verify Details"]) == 8


def test_report_review_detail_has_db_controls_and_seek(db_pages):
    rid = sorted(r["id"] for r in db_pages.list_reports())[0]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = str(rid)
    app.run()
    assert not app.exception
    # DB-only controls are present.
    assert any(b.label == "Save review status" for b in app.button)
    assert any("Link source video from Cloudflare R2" in m.value for m in app.markdown)
    # Jump-to-start uses the stored incident start (auto-seek path).
    assert any("Jump to incident start" in b.label for b in app.button)


def test_report_review_edit_persists_across_a_rerun(db_pages):
    rid = sorted(r["id"] for r in db_pages.list_reports())[0]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = str(rid)
    app.run()
    app.toggle[0].set_value(True).run()
    app.text_area[0].set_value("persisted through the database")
    next(b for b in app.button if b.label == "Save changes").click().run()
    assert not app.exception
    assert db_pages.get_report(rid)["description"] == "persisted through the database"


def test_dashboard_renders_charts_from_db_incidents(db_pages):
    app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=15).run()
    assert not app.exception
    assert app.metric[0].value == "8"
    # Evidence-driven widgets have content (entity donut / threat matrix).
    assert not any("No linked entities" in i.value for i in app.info)
