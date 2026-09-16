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
module docstring), ``incident_id`` here is the console's ``videos.id`` /
``incidents.incident_id`` - *not* necessarily the raw VST sensor id. The
console's own upload flow (``catalog_actions.derive_video_id()``) hashes the
raw sensor id into a 20-char id to fit the ``videos.id`` column, since real
sensor ids/filenames can run up to 128 chars. This route resolves the real
sensor id via ``incident_db`` before invoking ``incident_report_gen``, and
passes both ids through so persistence still keys off ``incident_id``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.workflow_builder import WorkflowBuilder
from pydantic import BaseModel, Field

from vss_agents.data_models.incident_report import IncidentReport
from vss_agents.utils import incident_db

logger = logging.getLogger(__name__)


async def _resolve_sensor_id(incident_id: str) -> str:
    """Resolve the real VST sensor id for a console ``incident_id``.

    The console stores the raw sensor id in ``videos.source`` (see
    ``catalog_actions.upload_and_record``). Falls back to ``incident_id``
    itself whenever the DB is unconfigured/unreachable, no row is found, or
    the row has no recorded source - never fails the request over this
    lookup, since callers that pass an already-real sensor id (e.g. a
    chat-driven flow with no console record) must keep working unchanged.
    """
    try:
        if not incident_db.is_configured():
            return incident_id
        db = await incident_db.get_db()
        if db is None:
            return incident_id
        video = await db.get_video(incident_id)
        if not video or not video.get("source"):
            return incident_id
        return video["source"]
    except Exception as exc:  # noqa: BLE001 - fail-soft, see docstring
        logger.warning("incident_analyze: failed to resolve sensor_id for %s: %s", incident_id, exc)
        return incident_id


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
            "Runs video_report_gen over the uploaded video identified by incident_id (the console's "
            "videos.id/incidents.incident_id, resolved to the real VST sensor id via the incident DB when "
            "configured), extracts a structured IncidentReport, persists it to the incident DB when "
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

        sensor_id = await _resolve_sensor_id(incident_id)
        tool_input: dict[str, Any] = {"sensor_id": sensor_id, "incident_id": incident_id}
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
