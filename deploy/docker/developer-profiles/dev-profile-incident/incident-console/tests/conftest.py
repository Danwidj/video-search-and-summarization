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

"""Hermetic fixtures - no live Postgres / agent / GPU."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db as _db  # noqa: E402
from db import IncidentDB  # noqa: E402


@pytest.fixture
def incident_db(tmp_path) -> IncidentDB:
    handle = IncidentDB.from_dsn(f"sqlite:///{tmp_path / 'incidents.db'}")
    handle.init_schema()
    return handle


@pytest.fixture(autouse=True)
def no_live_infra(monkeypatch):
    """Keep the whole suite hermetic.

    A developer's git-ignored ``.env.local`` (real Supabase DSN + R2 keys) is
    loaded by ``config`` on import. Scrub those here so tests never touch live
    infrastructure; a test that wants a database sets a SQLite DSN explicitly.
    """
    monkeypatch.setattr("r2_videos.configured", lambda: False)
    for name in ("INCIDENT_DB_DSN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    _db.reset_cache()
    yield
    _db.reset_cache()


@pytest.fixture
def db_reports(incident_db, monkeypatch):
    """A DB-backed report view model wired to the hermetic SQLite fixture."""
    from db_reports import DBReports

    monkeypatch.setattr("config.incident_db_dsn", lambda: str(incident_db.engine.url))
    _db.reset_cache()
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    return DBReports(incident_db)
