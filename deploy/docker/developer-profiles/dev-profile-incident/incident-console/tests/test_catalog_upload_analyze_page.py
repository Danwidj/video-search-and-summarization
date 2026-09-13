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

"""Catalog page: Analyze incident button renders the fail-soft 404/405/501 states calmly."""

from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import agent_client
from scripts.seed_supabase import seed


@pytest.fixture
def db_pages(incident_db, monkeypatch):
    seed(incident_db)
    monkeypatch.setattr("config.incident_db_dsn", lambda: str(incident_db.engine.url))
    monkeypatch.setattr("db.is_configured", lambda: True)
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    return incident_db


@pytest.mark.parametrize("code", [404, 405, 501])
def test_analyze_incident_button_renders_calm_message_when_not_implemented(db_pages, monkeypatch, code):
    monkeypatch.setattr(agent_client.httpx, "post", lambda *a, **k: httpx.Response(code))  # noqa: ARG005

    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    assert not app.exception

    analyze_button = next(b for b in app.button if b.label == "Analyze incident")
    analyze_button.click().run()

    assert not app.exception
    assert any("isn't available on this backend yet" in m.value for m in app.markdown)


def test_analyze_incident_button_renders_a_real_error_distinctly(db_pages, monkeypatch):
    monkeypatch.setattr(
        agent_client.httpx,
        "post",
        lambda *a, **k: httpx.Response(500, text="boom"),  # noqa: ARG005
    )

    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    analyze_button = next(b for b in app.button if b.label == "Analyze incident")
    analyze_button.click().run()

    assert not app.exception
    assert not any("isn't available on this backend yet" in m.value for m in app.markdown)
    assert any("Analyze failed" in m.value for m in app.markdown)
