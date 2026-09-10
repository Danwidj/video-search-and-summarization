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

"""Catalog and Severity Eval render from the database, and degrade with no DSN.

Mirrors ``test_pages_db_mode.py``: the database is the hermetic SQLite fixture
seeded from the CSV fixtures; R2 stays stubbed unconfigured.
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


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_catalog_loads_in_db_mode(db_pages):
    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    assert not app.exception
    assert app.dataframe
    assert app.dataframe[0].value.shape[0] == len(db_pages.list_videos())


def test_catalog_loads_without_db():
    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    assert not app.exception
    assert any("Database not configured" in m.value for m in app.markdown)


def test_catalog_filename_filter_narrows_the_list(db_pages):
    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    full = app.dataframe[0].value.shape[0]
    target = db_pages.list_videos_with_counts()[0]["filename"]

    app.text_input[0].set_value(target).run()
    assert not app.exception
    narrowed = app.dataframe[0].value.shape[0]
    assert 1 <= narrowed <= full

    app.text_input[0].set_value("zzz-no-such-clip").run()
    assert not app.exception
    assert not app.dataframe


def test_catalog_reports_column_counts_incidents(db_pages):
    rows = db_pages.list_videos_with_counts()
    assert rows
    assert all(row["report_count"] == 1 for row in rows)


# --------------------------------------------------------------------------- #
# Severity Eval
# --------------------------------------------------------------------------- #
def test_severity_eval_loads_in_db_mode(db_pages):
    app = AppTest.from_file("../pages/4_Severity_Eval.py", default_timeout=15).run()
    assert not app.exception
    assert any("Exact agreement rate" in m.label for m in app.metric) or any(
        "No ratings logged yet" in c.value for c in app.caption
    )


def test_severity_eval_loads_without_db():
    app = AppTest.from_file("../pages/4_Severity_Eval.py", default_timeout=15).run()
    assert not app.exception
    assert any("Database not configured" in m.value for m in app.markdown)


def test_severity_eval_submit_writes_a_log_row(db_pages):
    app = AppTest.from_file("../pages/4_Severity_Eval.py", default_timeout=15).run()
    assert not app.exception
    before = db_pages.severity_eval_counts()["total"]

    app.slider[0].set_value(3)
    next(t for t in app.text_input if t.label == "Rater").set_value("qa-bot")
    next(b for b in app.button if b.label == "Submit rating").click().run()
    assert not app.exception

    assert db_pages.severity_eval_counts()["total"] == before + 1
    latest = db_pages.list_severity_evals()[0]
    assert latest["rater"] == "qa-bot"
    assert latest["human_severity"] == 3
