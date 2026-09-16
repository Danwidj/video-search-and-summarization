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

from __future__ import annotations

import httpx
import pytest

import agent_client
from agent_client import AgentClient
from incident_report import IncidentReport, canned_incident_report, to_completion_payload


def _client_with_transport(handler, **kw) -> AgentClient:
    transport = httpx.MockTransport(handler)

    def fake_post(url, *, json=None, timeout=None, **kwargs):  # noqa: ARG001
        with httpx.Client(transport=transport) as c:
            if "files" in kwargs:
                return c.post(url, files=kwargs["files"], data=kwargs.get("data"))
            return c.post(url, json=json)

    return fake_post


def test_analyze_incident_fails_soft_on_404(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="").analyze_incident(7)
    assert res.ok is False
    assert res.not_implemented is True
    assert "not implemented" in res.error


def test_analyze_incident_uses_timeout_floor_for_synchronous_r2_upload(monkeypatch):
    """The default 15s timeout is too short for R2 upload + VLM inference."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "done"})

    inner = _client_with_transport(handler)

    def spy(url, *, json=None, timeout=None, **kwargs):
        seen["timeout"] = timeout
        return inner(url, json=json, timeout=timeout, **kwargs)

    monkeypatch.setattr(agent_client.httpx, "post", spy)
    res = AgentClient(base_url="http://agent", llm_base_url="").analyze_incident(7)
    assert res.ok is True
    assert seen["timeout"] == 120.0


def test_search_fails_soft_on_connection_error(monkeypatch):
    def boom(*args, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(agent_client.httpx, "post", boom)
    res = AgentClient(base_url="http://agent", llm_base_url="").search("weapon at door")
    assert res.ok is False
    assert "ConnectError" in res.error


def test_draft_report_via_llm_parses_completion(monkeypatch):
    payload = to_completion_payload(canned_incident_report("two vehicles collide at the junction"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="http://mock/v1").draft_report_via_llm(
        prompt="describe the incident"
    )
    assert res.ok is True
    assert isinstance(res.data, IncidentReport)
    assert res.data.incident_type == "road accident"


def test_draft_report_via_llm_requires_base_url():
    res = AgentClient(base_url="http://agent", llm_base_url="").draft_report_via_llm(prompt="x")
    assert res.ok is False
    assert "INCIDENT_LLM_BASE_URL" in res.error


def test_request_upload_url_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "http://vst/upload/abc"})

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="").request_upload_url("clip.mp4")
    assert res.ok is True
    assert res.data["url"] == "http://vst/upload/abc"


@pytest.mark.parametrize("code", [404, 405, 501])
def test_not_implemented_codes(monkeypatch, code):
    monkeypatch.setattr(
        agent_client.httpx,
        "post",
        _client_with_transport(lambda r: httpx.Response(code)),
    )
    res = AgentClient(base_url="http://agent", llm_base_url="").search("q")
    assert res.not_implemented is True


@pytest.mark.parametrize("code", [404, 405, 501])
def test_analyze_incident_not_implemented_renders_as_calm_message(monkeypatch, code):
    """Mirrors the message the Catalog page shows for a fail-soft response."""
    monkeypatch.setattr(
        agent_client.httpx,
        "post",
        _client_with_transport(lambda r: httpx.Response(code)),
    )
    res = AgentClient(base_url="http://agent", llm_base_url="").analyze_incident("v-abc123")
    assert res.ok is False
    assert res.not_implemented is True
    # A real error (ok=False, not_implemented=False) is the only case that
    # should ever read as a bug in the UI; this must not be that case.
    assert res.status_code == code


def test_upload_video_sends_mediaFile_field_and_filename_per_nvstreamer_protocol(monkeypatch):
    """Regression test for a real bug: the chunk POST used to send the file
    under form field ``file`` with no ``filename`` field, which the real VST
    protocol (and its mock, mirroring ``form.get('mediaFile')`` /
    ``form.get('filename')``) doesn't recognize - uploads silently landed
    with an empty body and a fallback filename instead of the real one.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/videos":
            return httpx.Response(200, json={"url": "http://vst/upload"})
        if request.url.path == "/upload":
            content_type = request.headers.get("content-type", "")
            assert content_type.startswith("multipart/form-data")
            body = request.content.decode("latin-1")
            seen["has_media_file_field"] = 'name="mediaFile"' in body
            seen["has_filename_field"] = 'name="filename"' in body and "clip.mp4" in body
            return httpx.Response(200, json={"sensorId": "sensor-abc", "filePath": "http://vst/clip.mp4"})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"message": "ok", "sensor_id": "sensor-abc", "filename": "clip.mp4"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="").upload_video(filename="clip.mp4", content=b"bytes")

    assert res.ok is True
    assert seen["has_media_file_field"] is True
    assert seen["has_filename_field"] is True


def test_upload_video_success_extracts_sensor_id_and_filepath(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/videos":
            return httpx.Response(200, json={"url": "http://vst/upload"})
        if request.url.path == "/upload":
            return httpx.Response(200, json={"filePath": "http://vst/videos/clip.mp4", "sensorId": "sensor-abc"})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"message": "ok", "sensor_id": "sensor-abc", "filename": "clip.mp4"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="").upload_video(filename="clip.mp4", content=b"bytes")

    assert res.ok is True
    assert res.data["sensor_id"] == "sensor-abc"
    assert res.data["filepath"] == "http://vst/videos/clip.mp4"


def test_upload_video_parses_json_body_sent_with_text_plain_content_type(monkeypatch):
    """Regression test for a real bug: the VST/nginx stack fronting the real
    chunked-upload endpoint responds with a JSON-shaped body but a
    ``Content-Type: text/plain`` header, not ``application/json``. Gating the
    parse on that header made the client silently discard the real body and
    fall back to ``{}``, so ``sensorId`` was always reported missing even
    though it was present.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/videos":
            return httpx.Response(200, json={"url": "http://vst/upload"})
        if request.url.path == "/upload":
            return httpx.Response(
                200,
                content=b'{"sensorId": "sensor-abc", "filePath": "http://vst/videos/clip.mp4"}',
                headers={"content-type": "text/plain"},
            )
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"message": "ok", "sensor_id": "sensor-abc", "filename": "clip.mp4"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="").upload_video(filename="clip.mp4", content=b"bytes")

    assert res.ok is True
    assert res.data["sensor_id"] == "sensor-abc"
    assert res.data["filepath"] == "http://vst/videos/clip.mp4"


def test_upload_video_falls_back_to_empty_body_on_unparseable_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/videos":
            return httpx.Response(200, json={"url": "http://vst/upload"})
        if request.url.path == "/upload":
            return httpx.Response(200, content=b"not json at all", headers={"content-type": "text/plain"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(handler))
    res = AgentClient(base_url="http://agent", llm_base_url="").upload_video(filename="clip.mp4", content=b"bytes")

    assert res.ok is False
    assert "did not return a sensorId" in res.error


def test_upload_video_falls_back_to_vst_url_when_chunk_response_lacks_filepath(monkeypatch):
    def post_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/videos":
            return httpx.Response(200, json={"url": "http://vst/upload"})
        if request.url.path == "/upload":
            return httpx.Response(200, json={"sensorId": "sensor-abc"})  # no filePath
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"message": "ok", "sensor_id": "sensor-abc", "filename": "clip.mp4"})
        raise AssertionError(f"unexpected request: {request.url}")

    def get_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/vst/api/v1/storage/file/sensor-abc/url"
        return httpx.Response(200, json={"videoUrl": "http://vst/videos/clip.mp4"})

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(post_handler))

    transport = httpx.MockTransport(get_handler)

    def fake_get(url, *, timeout=None, **kwargs):  # noqa: ARG001
        with httpx.Client(transport=transport) as c:
            return c.get(url)

    monkeypatch.setattr(agent_client.httpx, "get", fake_get)

    res = AgentClient(base_url="http://agent", llm_base_url="").upload_video(filename="clip.mp4", content=b"bytes")
    assert res.ok is True
    assert res.data["filepath"] == "http://vst/videos/clip.mp4"


def test_upload_video_resolves_internal_filepath_through_vst(monkeypatch):
    """The local mock's internal file path must not be persisted as a dead URL."""

    def post_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/videos":
            return httpx.Response(200, json={"url": "http://vst/upload"})
        if request.url.path == "/upload":
            return httpx.Response(200, json={"sensorId": "sensor-abc", "filePath": "/data/videos/clip.mp4"})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"message": "ok"})
        raise AssertionError(f"unexpected request: {request.url}")

    def get_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/vst/api/v1/storage/file/sensor-abc/url"
        return httpx.Response(200, json={"videoUrl": "http://vst/videos/clip.mp4"})

    monkeypatch.setattr(agent_client.httpx, "post", _client_with_transport(post_handler))
    transport = httpx.MockTransport(get_handler)

    def fake_get(url, *, timeout=None, **kwargs):  # noqa: ARG001
        with httpx.Client(transport=transport) as c:
            return c.get(url)

    monkeypatch.setattr(agent_client.httpx, "get", fake_get)
    result = AgentClient(base_url="http://agent", llm_base_url="").upload_video(filename="clip.mp4", content=b"bytes")

    assert result.ok is True
    assert result.data["filepath"] == "http://vst/videos/clip.mp4"
