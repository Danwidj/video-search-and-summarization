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

"""Unit tests for ``POST /api/v1/incidents/charts``."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vss_agents.api.incident_charts import register_incident_charts_routes
from vss_agents.tools.chart_generator import ChartGenExecOutput

BODY = {
    "charts_data": [
        {
            "chart_file_format": "png",
            "title": "Reports by incident type",
            "x_categories": ["Assault", "Burglary"],
            "series": {"Official": [1, 0], "Not official": [4, 2]},
            "x_label": "Incident type",
            "y_label": "Reports",
        }
    ],
    "output_dir": "dashboard-charts",
    "file_prefix": "abc_",
}
OUTPUT = [ChartGenExecOutput(success=True, error_message=None, object_store_key="dashboard-charts/abc_0.png")]


def _client(tool=None, *, configured=True) -> TestClient:
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=tool) if configured else AsyncMock(side_effect=ValueError("no such tool"))
    app = FastAPI()
    register_incident_charts_routes(app, builder)
    return TestClient(app)


def test_passes_the_figures_to_the_tool_and_returns_the_image_key():
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value=OUTPUT)
    response = _client(tool).post("/api/v1/incidents/charts", json=BODY)
    assert response.status_code == 200
    assert response.json() == [
        {"success": True, "error_message": None, "object_store_key": "dashboard-charts/abc_0.png"}
    ]
    sent = tool.ainvoke.await_args.args[0]
    assert sent["charts_data"][0]["series"] == {"Official": [1.0, 0.0], "Not official": [4.0, 2.0]}
    assert sent["output_dir"] == "dashboard-charts"
    assert sent["file_prefix"] == "abc_"


def test_draws_a_pie():
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value=OUTPUT)
    pie = {
        "chart_file_format": "png",
        "title": "Reports by severity",
        "sizes": [3, 1],
        "labels": ["Low (3)", "High (1)"],
    }
    response = _client(tool).post("/api/v1/incidents/charts", json={**BODY, "charts_data": [pie]})
    assert response.status_code == 200
    assert tool.ainvoke.await_args.args[0]["charts_data"][0]["labels"] == ["Low (3)", "High (1)"]


def test_a_request_without_figures_is_refused_before_the_tool():
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value=OUTPUT)
    response = _client(tool).post("/api/v1/incidents/charts", json={"charts_data": [{"title": "no figures"}]})
    assert response.status_code == 422
    tool.ainvoke.assert_not_awaited()


def test_a_profile_without_the_tool_gets_501():
    response = _client(configured=False).post("/api/v1/incidents/charts", json=BODY)
    assert response.status_code == 501


def test_a_tool_failure_is_a_plain_500():
    tool = MagicMock()
    tool.ainvoke = AsyncMock(side_effect=RuntimeError("object store path /secret failed"))
    response = _client(tool).post("/api/v1/incidents/charts", json=BODY)
    assert response.status_code == 500
    assert "secret" not in response.text
