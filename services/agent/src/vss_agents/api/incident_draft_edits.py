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

"""``POST /api/v1/incidents/{video_id}/draft-edits`` - check proposed edits against the reviewer's unsaved draft.

Off unless ``INCIDENT_DRAFT_EDITS_ENABLED`` is set: a request is then a ``404``. The route checks each call the agent
makes and returns the proposals that pass, with a reason for each that does not. It writes nothing: the console applies
the proposals to the draft, and the reviewer saves. See :mod:`vss_agents.utils.draft_edits`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.utils import draft_edits

logger = logging.getLogger(__name__)

MAX_CALLS = 6


class DraftEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: draft_edits.DraftSnapshot
    calls: list[draft_edits.Call] = Field(min_length=1, max_length=MAX_CALLS)


def create_incident_draft_edits_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/{video_id}/draft-edits",
        response_model=draft_edits.ProposalResult,
        summary="Check proposed edits against the unsaved draft; writes nothing",
        tags=["Incident Chat"],
    )
    async def propose_draft_edits(video_id: str, body: DraftEditRequest) -> draft_edits.ProposalResult:
        if not draft_edits.enabled():
            raise HTTPException(status_code=404, detail="Draft edits are not enabled on this agent")
        result = draft_edits.propose(body.draft, body.calls)
        logger.info(
            "Draft edits for %s: %d proposed, %d rejected", video_id, len(result.proposals), len(result.rejected)
        )
        return result

    return router


def register_incident_draft_edits_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/{video_id}/draft-edits`` onto the FastAPI app."""
    app.include_router(create_incident_draft_edits_router())
    logger.info("Registered POST /api/v1/incidents/{video_id}/draft-edits")
