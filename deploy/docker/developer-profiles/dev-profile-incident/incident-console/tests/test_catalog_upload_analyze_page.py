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
import r2_videos
from scripts.seed_supabase import seed


def _mock_upload_transport(analyze_code: int):
    """Create a mock transport that handles the 3-step upload flow + analyze endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/videos":
            # Step 1: request_upload_url
            return httpx.Response(200, json={"url": "http://mock/upload"})
        if path == "/upload":
            # Step 2: chunked upload to nvstreamer
            return httpx.Response(200, json={"sensorId": "sensor-test123", "filePath": "/tmp/test.mp4"})
        if path.endswith("/complete"):
            # Step 3: complete_upload
            return httpx.Response(200, json={})
        if path.startswith("/api/v1/incidents/") and path.endswith("/analyze"):
            # analyze_incident endpoint for any video ID
            return httpx.Response(analyze_code, text="not implemented" if analyze_code in (404, 405, 501) else "boom")
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def _fake_post_with_transport(transport: httpx.MockTransport):
    def fake_post(url, *, json=None, timeout=None, files=None, data=None, **kwargs):  # noqa: ARG001
        with httpx.Client(transport=transport) as c:
            if files is not None:
                return c.post(url, files=files, data=data, timeout=timeout)
            return c.post(url, json=json, timeout=timeout)

    return fake_post


@pytest.fixture
def db_pages(incident_db, monkeypatch):
    seed(incident_db)
    monkeypatch.setattr("config.incident_db_dsn", lambda: str(incident_db.engine.url))
    monkeypatch.setattr("db.is_configured", lambda: True)
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    return incident_db


@pytest.mark.parametrize("code", [404, 405, 501])
def test_analyze_incident_button_renders_calm_message_when_not_implemented(db_pages, monkeypatch, code):
    transport = _mock_upload_transport(code)
    monkeypatch.setattr(agent_client.httpx, "post", _fake_post_with_transport(transport))  # noqa: ARG005
    # Mock R2 download to return dummy video bytes
    monkeypatch.setattr(r2_videos, "download_video_bytes", lambda key: b"fake video content")

    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    assert not app.exception

    analyze_button = next(b for b in app.button if b.label == "Analyze incident")
    analyze_button.click().run()

    assert not app.exception
    assert any("isn't available on this backend yet" in m.value for m in app.markdown)


def test_analyze_incident_button_renders_a_real_error_distinctly(db_pages, monkeypatch):
    transport = _mock_upload_transport(500)
    monkeypatch.setattr(agent_client.httpx, "post", _fake_post_with_transport(transport))  # noqa: ARG005
    # Mock R2 download to return dummy video bytes
    monkeypatch.setattr(r2_videos, "download_video_bytes", lambda key: b"fake video content")

    app = AppTest.from_file("../pages/1_Catalog.py", default_timeout=15).run()
    analyze_button = next(b for b in app.button if b.label == "Analyze incident")
    analyze_button.click().run()

    assert not app.exception
    assert not any("isn't available on this backend yet" in m.value for m in app.markdown)
    assert any("Analyze failed" in m.value for m in app.markdown)
