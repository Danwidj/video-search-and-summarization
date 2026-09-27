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

"""Unit tests for ``POST /api/v1/incidents/{incident_id}/analyze`` on the incident contract."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from vss_agents.api.incident_analyze import register_incident_analyze_routes
from vss_agents.incident_contract import IncidentExtractionError
from vss_agents.tools.incident_report_gen import IncidentReportGenOutput

VIDEO_URL = "https://r2.example/uploads/cam/clip.mp4?X-Amz-Signature=abc"
OUTPUT = IncidentReportGenOutput(
    report={"incident": {"type": "burglary", "duration": 5}},
    report_text="INCIDENT REPORT",
    report_text_error=None,
    model="nvidia/cosmos-3-nano-reasoner",
    contract_version="incident-contract-v2",
    raw_output="{}",
)


def _client(*, result=None, side_effect=None, tool_missing=False) -> tuple[TestClient, MagicMock]:
    app = FastAPI()
    builder = MagicMock()
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value=result, side_effect=side_effect)
    builder.get_tool = (
        AsyncMock(side_effect=RuntimeError("not configured")) if tool_missing else AsyncMock(return_value=tool)
    )
    register_incident_analyze_routes(app, config=MagicMock(), builder=builder)
    return TestClient(app), tool


def test_passes_incident_id_video_url_and_model_run_id_to_the_tool():
    client, tool = _client(result=OUTPUT)
    response = client.post("/api/v1/incidents/v1/analyze", json={"video_url": VIDEO_URL, "model_run_id": "run1"})
    assert response.status_code == 200
    tool.ainvoke.assert_awaited_once_with({"incident_id": "v1", "video_url": VIDEO_URL, "model_run_id": "run1"})
    assert response.json() == OUTPUT.model_dump()


def test_video_url_is_required():
    client, tool = _client(result=OUTPUT)
    assert client.post("/api/v1/incidents/v1/analyze", json={}).status_code == 422
    tool.ainvoke.assert_not_called()


def test_old_body_fields_are_not_accepted_in_place_of_video_url():
    client, _ = _client(result=OUTPUT)
    response = client.post("/api/v1/incidents/v1/analyze", json={"prompt_override": "x", "reasoning": True})
    assert response.status_code == 422


def test_contract_violation_is_422():
    client, _ = _client(side_effect=IncidentExtractionError("schema violation: incident/type"))
    response = client.post("/api/v1/incidents/v1/analyze", json={"video_url": VIDEO_URL})
    assert response.status_code == 422
    assert "schema violation" in response.json()["detail"]


def test_timeout_is_504():
    client, _ = _client(side_effect=TimeoutError("slow"))
    assert client.post("/api/v1/incidents/v1/analyze", json={"video_url": VIDEO_URL}).status_code == 504


def test_other_failure_is_500():
    client, _ = _client(side_effect=RuntimeError("boom"))
    assert client.post("/api/v1/incidents/v1/analyze", json={"video_url": VIDEO_URL}).status_code == 500


def test_missing_tool_is_501():
    client, _ = _client(tool_missing=True)
    assert client.post("/api/v1/incidents/v1/analyze", json={"video_url": VIDEO_URL}).status_code == 501
