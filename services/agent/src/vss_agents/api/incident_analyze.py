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

``incident-console-v2`` (agent mode) calls this route with the console's ``videos.id`` as
``incident_id`` and a signed R2 URL for the uploaded video. The route runs the
``incident_report_gen`` tool - the shared incident contract's P1 -> RP1 calls - and returns
the validated contract report plus the ``report_revisions`` id of the AI revision the agent
inserted (``revision_id``). Re-generation is the same call with an optional ``model`` and a
human-typed ``reviewer_prompt``; it starts a new AI revision and copies nothing from earlier ones.
The agent needs no VST lookup: the console owns the ``videos`` row and signs the URL.

Status codes: 422 when the model output fails ``core-scored-v1`` (nothing is persisted; the
detail carries ``message``, ``raw_output``, ``finish_reason``, ``model`` and ``contract_version``
so the caller can record the attempt), 400 for a ``model`` outside the contract allowlist,
504 on a P1 timeout, 501 when the profile does not configure ``incident_report_gen``,
500 for anything else.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from nat.builder.framework_enum import LLMFrameworkEnum
from pydantic import BaseModel
from pydantic import Field

from vss_agents.incident_contract import IncidentExtractionError
from vss_agents.incident_contract import allowed_models
from vss_agents.incident_contract import contract_version
from vss_agents.tools.incident_report_gen import MAX_REVIEWER_PROMPT_LENGTH

if TYPE_CHECKING:
    from nat.builder.workflow_builder import WorkflowBuilder

logger = logging.getLogger(__name__)


class AnalyzeIncidentRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/{incident_id}/analyze``."""

    video_url: str = Field(..., min_length=1, description="Signed R2 URL of the uploaded video.")
    model_run_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description=(
            "The caller's model_runs.id; when given, the caller owns the run's notes and the agent only "
            "makes sure the row exists so the AI revision can reference it."
        ),
    )
    model: str | None = Field(
        default=None, min_length=1, description="Model id from the contract allowlist; defaults to the profile's."
    )
    reviewer_prompt: str | None = Field(
        default=None,
        max_length=MAX_REVIEWER_PROMPT_LENGTH,
        description="Extra reviewer text typed by a human, added to the report prompt for this run only.",
    )
    skip_rp1: bool = Field(
        default=False, description="Run P1 only (incident-console-v2 agent mode); report_text stays null."
    )


def create_incident_analyze_router(config: Any, builder: WorkflowBuilder) -> APIRouter:  # noqa: ARG001
    """Build the ``POST /api/v1/incidents/{incident_id}/analyze`` router.

    ``builder`` is captured once at router-build time and used to resolve the
    ``incident_report_gen`` tool per request.
    """
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/{incident_id}/analyze",
        summary="Extract a contract incident report from an uploaded video (P1) and write a prose report (RP1)",
        tags=["Incident Analyze"],
    )
    async def analyze_incident(incident_id: str, body: AnalyzeIncidentRequest) -> dict[str, Any]:
        if body.model and body.model not in allowed_models():
            raise HTTPException(
                status_code=400, detail=f"Model {body.model!r} is not in the incident contract allowlist"
            )

        try:
            incident_report_gen_tool = await builder.get_tool(
                "incident_report_gen", wrapper_type=LLMFrameworkEnum.LANGCHAIN
            )
        except Exception as exc:
            logger.error("incident_report_gen tool is not configured: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=501, detail="incident_report_gen tool is not configured on this profile"
            ) from exc

        tool_input: dict[str, Any] = {
            "incident_id": incident_id,
            "video_url": body.video_url,
            "skip_rp1": body.skip_rp1,
        }
        if body.model_run_id:
            tool_input["model_run_id"] = body.model_run_id
        if body.model:
            tool_input["model"] = body.model
        if body.reviewer_prompt:
            tool_input["reviewer_prompt"] = body.reviewer_prompt

        try:
            result = await incident_report_gen_tool.ainvoke(tool_input)
        except IncidentExtractionError as exc:
            logger.error("/analyze contract violation for incident_id=%s: %s", incident_id, exc)
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Incident contract violation: {exc}",
                    "raw_output": exc.raw_output,
                    "finish_reason": exc.finish_reason,
                    "model": exc.model,
                    "contract_version": contract_version(),
                },
            ) from exc
        except TimeoutError as exc:
            logger.error("/analyze timed out for incident_id=%s: %s", incident_id, exc)
            raise HTTPException(status_code=504, detail=f"Incident analysis timed out: {exc}") from exc
        except Exception as exc:
            logger.error("/analyze failed for incident_id=%s: %s", incident_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc
        return result.model_dump() if hasattr(result, "model_dump") else dict(result)

    return router


def register_incident_analyze_routes(app: FastAPI, config: Any, builder: WorkflowBuilder) -> None:
    """Register ``POST /api/v1/incidents/{incident_id}/analyze``.

    The route is always mounted. Profiles that don't configure the
    ``incident_report_gen`` tool get a 501 at request time (the tool is
    resolved per request), so unconditional registration is safe.
    """
    try:
        app.include_router(create_incident_analyze_router(config, builder))
        logger.info("Registered POST /api/v1/incidents/{incident_id}/analyze")
    except Exception as exc:
        logger.error("Failed to register incident analyze route: %s", exc, exc_info=True)
        raise
