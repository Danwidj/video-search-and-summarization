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

"""Unit tests for ``POST /api/v1/incidents/{video_id}/draft-edits`` (flag, validation, no writes)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vss_agents.api.incident_draft_edits import register_incident_draft_edits_routes

DRAFT = {
    "incident": {"type": "burglary", "title": "Shop", "start_timestamp": 10, "end_timestamp": 60},
    "entities": [{"key": "entity-0", "type": "human", "first_seen_seconds": 12, "last_seen_seconds": 40}],
    "instruments": [],
    "assets": [],
}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_incident_draft_edits_routes(app)
    return TestClient(app)


def test_route_returns_proposals_and_rejections(client: TestClient) -> None:
    body = {
        "draft": DRAFT,
        "calls": [
            {"tool": "set_incident_fields", "args": {"severity_level": 3}},
            {"tool": "set_timeline_item", "args": {"item_key": "entity-9", "label": "x"}},
        ],
    }
    response = client.post("/api/v1/incidents/vid-1/draft-edits", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert [p["tool"] for p in payload["proposals"]] == ["set_incident_fields"]
    assert [r["tool"] for r in payload["rejected"]] == ["set_timeline_item"]


def test_route_refuses_more_calls_than_the_cap(client: TestClient) -> None:
    call = {"tool": "delete_item", "args": {"item_key": "entity-0"}}
    response = client.post("/api/v1/incidents/vid-1/draft-edits", json={"draft": DRAFT, "calls": [call] * 7})
    assert response.status_code == 422


def test_route_rejects_unknown_request_fields(client: TestClient) -> None:
    body = {"draft": DRAFT, "calls": [{"tool": "delete_item", "args": {"item_key": "entity-0"}}], "save": True}
    response = client.post("/api/v1/incidents/vid-1/draft-edits", json=body)
    assert response.status_code == 422
