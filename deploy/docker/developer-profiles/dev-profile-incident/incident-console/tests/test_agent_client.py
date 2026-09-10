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
                return c.post(url, files=kwargs["files"])
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
