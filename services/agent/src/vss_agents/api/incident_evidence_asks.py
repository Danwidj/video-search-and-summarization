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

"""``POST /api/v1/incidents/{video_id}/evidence-asks`` - check the orchestrator's new-evidence calls.

Off unless ``INCIDENT_EVIDENCE_ASKS_ENABLED`` is set: a request is then a ``404``. The route checks each call and returns
the proposals that pass, with a reason for each that does not. It writes nothing and asks nothing: the console puts a
question in the chat and opens the box tool. See :mod:`vss_agents.utils.evidence_asks`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.utils import evidence_asks

logger = logging.getLogger(__name__)

MAX_CALLS = 6


class EvidenceAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident: evidence_asks.IncidentWindow | None = None
    questions_asked: int = Field(0, ge=0, le=evidence_asks.MAX_QUESTIONS)
    calls: list[evidence_asks.Call] = Field(min_length=1, max_length=MAX_CALLS)


def create_incident_evidence_asks_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/{video_id}/evidence-asks",
        response_model=evidence_asks.ProposalResult,
        summary="Check new-evidence questions and the box tool opening; writes nothing",
        tags=["Incident Chat"],
    )
    async def propose_evidence_asks(video_id: str, body: EvidenceAskRequest) -> evidence_asks.ProposalResult:
        if not evidence_asks.enabled():
            raise HTTPException(status_code=404, detail="Evidence questions are not enabled on this agent")
        result = evidence_asks.propose(body.incident, body.questions_asked, body.calls)
        logger.info(
            "Evidence asks for %s: %d proposed, %d rejected", video_id, len(result.proposals), len(result.rejected)
        )
        return result

    return router


def register_incident_evidence_asks_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/{video_id}/evidence-asks`` onto the FastAPI app."""
    app.include_router(create_incident_evidence_asks_router())
    logger.info("Registered POST /api/v1/incidents/{video_id}/evidence-asks")
