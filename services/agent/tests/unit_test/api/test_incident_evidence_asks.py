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

"""Unit tests for ``POST /api/v1/incidents/{video_id}/evidence-asks`` (validation, no writes)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vss_agents.api.incident_evidence_asks import register_incident_evidence_asks_routes

URL = "/api/v1/incidents/vid-1/evidence-asks"
INCIDENT = {"start_timestamp": 10, "end_timestamp": 60}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_incident_evidence_asks_routes(app)
    return TestClient(app)


def test_route_returns_proposals_and_rejections(client: TestClient) -> None:
    body = {
        "incident": INCIDENT,
        "questions_asked": 2,
        "calls": [
            {"tool": "ask_reviewer", "args": {"question": "Who?"}},
            {"tool": "open_box_tool", "args": {"seconds": 30, "name": "Bag"}},
        ],
    }
    response = client.post(URL, json=body)
    assert response.status_code == 200
    data = response.json()
    assert [p["tool"] for p in data["proposals"]] == ["open_box_tool"]
    assert [r["tool"] for r in data["rejected"]] == ["ask_reviewer"]


def test_route_proposes_the_box_tool_opening(client: TestClient) -> None:
    body = {
        "incident": INCIDENT,
        "questions_asked": 1,
        "calls": [
            {"tool": "ask_reviewer", "args": {"question": "Who?"}},
            {"tool": "open_box_tool", "args": {"seconds": 30, "name": "Bag"}},
        ],
    }
    data = client.post(URL, json=body).json()
    assert [p["tool"] for p in data["proposals"]] == ["ask_reviewer", "open_box_tool"]
    assert data["proposals"][1]["args"] == {"seconds": 30, "name": "Bag"}
    assert data["rejected"] == []


def test_route_refuses_more_than_two_questions_already_asked(client: TestClient) -> None:
    body = {"questions_asked": 3, "calls": [{"tool": "ask_reviewer", "args": {"question": "Who?"}}]}
    response = client.post(URL, json=body)
    assert response.status_code == 422


def test_route_refuses_unknown_body_fields(client: TestClient) -> None:
    body = {"calls": [{"tool": "ask_reviewer", "args": {"question": "Who?"}}], "draft": {}}
    response = client.post(URL, json=body)
    assert response.status_code == 422


def test_route_requires_at_least_one_call(client: TestClient) -> None:
    response = client.post(URL, json={"calls": []})
    assert response.status_code == 422
