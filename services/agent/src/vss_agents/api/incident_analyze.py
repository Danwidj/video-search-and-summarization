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

"""``POST /api/v1/incidents/{incident_id}/analyze`` - the incident-console AI trigger.

The console's ``agent_client.py::analyze_incident`` calls this route to turn
an uploaded video into a persisted, structured incident report. Per the
incident-console schema's identity rule (1 video = 1 incident,
``incidents.incident_id`` == ``videos.id``, see
``deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py``'s
module docstring), ``incident_id`` here is the same VST sensor id
(filename) used everywhere else in the agent's video APIs - no separate
lookup is required to turn one into the other.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.workflow_builder import WorkflowBuilder
from pydantic import BaseModel, Field

from vss_agents.data_models.incident_report import IncidentReport

logger = logging.getLogger(__name__)


class AnalyzeIncidentRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/{incident_id}/analyze``."""

    reasoning: bool | None = Field(default=None, description="Enable VLM reasoning mode for video analysis.")
    prompt_override: str | None = Field(
        default=None, description="Optional override for the analysis prompt sent to video_report_gen."
    )


def create_incident_analyze_router(config: Any, builder: WorkflowBuilder) -> APIRouter:
    """Build the ``POST /api/v1/incidents/{incident_id}/analyze`` router.

    ``builder`` is captured once at router-build time and used to resolve the
    ``incident_report_gen`` tool per request (mirrors how other custom routes
    resolve their tools; see ``api/video_ingest.py``'s ``create_*_router``
    factories for the shape).
    """
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/{incident_id}/analyze",
        response_model=IncidentReport,
        summary="Analyze an uploaded video and produce a structured incident report",
        description=(
            "Runs video_report_gen over the uploaded video identified by incident_id (VST sensor id / "
            "filename), extracts a structured IncidentReport, persists it to the incident DB when "
            "configured, and returns the IncidentReport."
        ),
        tags=["Incident Analyze"],
    )
    async def analyze_incident(incident_id: str, body: AnalyzeIncidentRequest) -> IncidentReport:
        try:
            incident_report_gen_tool = await builder.get_tool(
                "incident_report_gen", wrapper_type=LLMFrameworkEnum.LANGCHAIN
            )
        except Exception as exc:
            logger.error("incident_report_gen tool is not configured: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=501, detail="incident_report_gen tool is not configured on this profile"
            ) from exc

        tool_input: dict[str, Any] = {"sensor_id": incident_id}
        if body.reasoning is not None:
            tool_input["vlm_reasoning"] = body.reasoning
        if body.prompt_override:
            tool_input["prompt_override"] = body.prompt_override

        try:
            result = await incident_report_gen_tool.ainvoke(tool_input)
        except Exception as exc:
            logger.error("/analyze failed for incident_id=%s: %s", incident_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

        return result.structured_report

    return router


def register_incident_analyze_routes(app: FastAPI, config: Any, builder: WorkflowBuilder) -> None:
    """Register ``POST /api/v1/incidents/{incident_id}/analyze``.

    Unlike the streaming_ingest routes, this one is not registered
    unconditionally - profiles that don't configure the ``incident_report_gen``
    tool simply won't have it resolve at request time (501), so it is safe to
    always mount the route.
    """
    try:
        app.include_router(create_incident_analyze_router(config, builder))
        logger.info("Registered POST /api/v1/incidents/{incident_id}/analyze")
    except Exception as exc:
        logger.error("Failed to register incident analyze route: %s", exc, exc_info=True)
        raise
