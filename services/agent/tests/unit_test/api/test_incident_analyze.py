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
"""Unit tests for the incident-console /analyze route's sensor_id resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vss_agents.api.incident_analyze import _resolve_sensor_id
from vss_agents.api.incident_analyze import register_incident_analyze_routes
from vss_agents.data_models.incident_report import IncidentReport


class TestResolveSensorId:
    """The console's incident_id is its own hashed videos.id, not the raw VST sensor
    id - this helper must translate one into the other via videos.source, and must
    never raise or block the request when that lookup can't be completed."""

    @pytest.mark.asyncio
    async def test_falls_back_to_incident_id_when_db_not_configured(self):
        with patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=False):
            assert await _resolve_sensor_id("v0123456789abcdef01") == "v0123456789abcdef01"

    @pytest.mark.asyncio
    async def test_falls_back_to_incident_id_when_pool_unavailable(self):
        with (
            patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=True),
            patch("vss_agents.api.incident_analyze.incident_db.get_db", new_callable=AsyncMock, return_value=None),
        ):
            assert await _resolve_sensor_id("v0123456789abcdef01") == "v0123456789abcdef01"

    @pytest.mark.asyncio
    async def test_resolves_real_sensor_id_from_videos_source(self):
        mock_db = AsyncMock()
        mock_db.get_video.return_value = {"id": "v0123456789abcdef01", "source": "camera-uploads/dock-b.mp4"}
        with (
            patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=True),
            patch("vss_agents.api.incident_analyze.incident_db.get_db", new_callable=AsyncMock, return_value=mock_db),
        ):
            resolved = await _resolve_sensor_id("v0123456789abcdef01")
        assert resolved == "camera-uploads/dock-b.mp4"
        mock_db.get_video.assert_awaited_once_with("v0123456789abcdef01")

    @pytest.mark.asyncio
    async def test_falls_back_to_incident_id_when_no_row_found(self):
        mock_db = AsyncMock()
        mock_db.get_video.return_value = None
        with (
            patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=True),
            patch("vss_agents.api.incident_analyze.incident_db.get_db", new_callable=AsyncMock, return_value=mock_db),
        ):
            assert await _resolve_sensor_id("v0123456789abcdef01") == "v0123456789abcdef01"

    @pytest.mark.asyncio
    async def test_falls_back_to_incident_id_when_lookup_raises(self):
        mock_db = AsyncMock()
        mock_db.get_video.side_effect = RuntimeError("connection reset")
        with (
            patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=True),
            patch("vss_agents.api.incident_analyze.incident_db.get_db", new_callable=AsyncMock, return_value=mock_db),
        ):
            assert await _resolve_sensor_id("v0123456789abcdef01") == "v0123456789abcdef01"


class TestAnalyzeIncidentRoute:
    """Drives the real registered route end-to-end (mocking only the NAT builder
    boundary and incident_db) to confirm both the resolved sensor_id and the
    original incident_id reach the incident_report_gen tool."""

    def _build_app(self, *, resolved_source: str | None):
        app = FastAPI()
        builder = MagicMock()
        incident_report_gen_tool = MagicMock()
        incident_report_gen_tool.ainvoke = AsyncMock(
            return_value=MagicMock(structured_report=IncidentReport(incident_type="fighting"))
        )
        builder.get_tool = AsyncMock(return_value=incident_report_gen_tool)
        register_incident_analyze_routes(app, config=MagicMock(), builder=builder)

        mock_db = AsyncMock()
        mock_db.get_video.return_value = {"source": resolved_source} if resolved_source else None
        return app, incident_report_gen_tool, mock_db

    def test_resolved_sensor_id_and_original_incident_id_both_reach_the_tool(self):
        app, tool, mock_db = self._build_app(resolved_source="camera-uploads/dock-b.mp4")
        with (
            patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=True),
            patch("vss_agents.api.incident_analyze.incident_db.get_db", new_callable=AsyncMock, return_value=mock_db),
        ):
            client = TestClient(app)
            response = client.post("/api/v1/incidents/v0123456789abcdef01/analyze", json={})

        assert response.status_code == 200
        tool_input = tool.ainvoke.await_args.args[0]
        assert tool_input["sensor_id"] == "camera-uploads/dock-b.mp4"
        assert tool_input["incident_id"] == "v0123456789abcdef01"

    def test_uses_incident_id_as_sensor_id_when_db_unconfigured(self):
        app, tool, _ = self._build_app(resolved_source=None)
        with patch("vss_agents.api.incident_analyze.incident_db.is_configured", return_value=False):
            client = TestClient(app)
            response = client.post("/api/v1/incidents/chat-driven-sensor.mp4/analyze", json={})

        assert response.status_code == 200
        tool_input = tool.ainvoke.await_args.args[0]
        assert tool_input["sensor_id"] == "chat-driven-sensor.mp4"
        assert tool_input["incident_id"] == "chat-driven-sensor.mp4"
