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

"""Tests for the report PDF: the Markdown-to-HTML step, image fetching, and ``POST /api/v1/incidents/report-pdf``."""

import base64
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from vss_agents.api.incident_report_pdf import MAX_IMAGES
from vss_agents.api.incident_report_pdf import register_incident_report_pdf_routes
from vss_agents.utils import incident_report_pdf

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
IMAGE_URL = "https://signed.example.test/evidence/v1/E1.png?X-Amz-Signature=secret-signature"
REPORT = """# Physical confrontation

| Field | Value |
|-------|-------|
| **Type** | Assault |

## People Involved

### Person 1

![Snapshot at 0:01](https://signed.example.test/evidence/v1/E1.png?X-Amz-Signature=secret-signature)
"""


def _client(status: int, body: bytes = PNG) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_image_refs_lists_each_image_in_order() -> None:
    refs = incident_report_pdf.image_refs(REPORT + "\n![second](https://example.test/b.jpg)")
    assert [ref.alt for ref in refs] == ["Snapshot at 0:01", "second"]


def test_markdown_renders_the_vss_tables_and_headings() -> None:
    html = incident_report_pdf.markdown_to_html(REPORT, {IMAGE_URL: PNG})
    assert "<table>" in html and "<td>" in html
    assert "<h2>People Involved</h2>" in html
    assert "data:image/png;base64," in html


def test_an_unavailable_image_becomes_a_note_not_a_broken_picture() -> None:
    html = incident_report_pdf.markdown_to_html(REPORT, {IMAGE_URL: None})
    assert "Snapshot unavailable: Snapshot at 0:01" in html
    assert "<img" not in html


@pytest.mark.asyncio
async def test_build_pdf_embeds_a_fetched_image_and_counts_the_missing_ones() -> None:
    pdf, missing = await incident_report_pdf.build_pdf(REPORT, "Incident report", "v4", _client(200))
    assert pdf.startswith(b"%PDF")
    assert missing == 0

    pdf, missing = await incident_report_pdf.build_pdf(REPORT, "Incident report", "v4", _client(404))
    assert pdf.startswith(b"%PDF")
    assert missing == 1


@pytest.mark.asyncio
async def test_an_oversized_image_is_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(incident_report_pdf, "MAX_IMAGE_BYTES", 10)
    assert await incident_report_pdf.fetch_image(_client(200), IMAGE_URL) is None


def _app() -> TestClient:
    app = FastAPI()
    register_incident_report_pdf_routes(app)
    return TestClient(app)


def test_the_route_returns_a_pdf_for_a_text_only_report() -> None:
    response = _app().post("/api/v1/incidents/report-pdf", json={"markdown": "# Report\n\nA summary."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-missing-images"] == "0"
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"%PDF")


def test_the_route_refuses_an_empty_report() -> None:
    assert _app().post("/api/v1/incidents/report-pdf", json={"markdown": ""}).status_code == 422


def test_the_route_refuses_a_report_with_too_many_images() -> None:
    markdown = "\n".join(f"![n](https://example.test/{i}.png)" for i in range(MAX_IMAGES + 1))
    response = _app().post("/api/v1/incidents/report-pdf", json={"markdown": markdown})
    assert response.status_code == 422


def test_the_route_rejects_unknown_fields() -> None:
    response = _app().post("/api/v1/incidents/report-pdf", json={"markdown": "# x", "store": True})
    assert response.status_code == 422


def test_a_signed_url_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    _app().post("/api/v1/incidents/report-pdf", json={"markdown": REPORT})
    assert "secret-signature" not in caplog.text
    assert "signed.example.test" not in caplog.text
