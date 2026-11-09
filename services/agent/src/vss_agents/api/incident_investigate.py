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

"""``POST /api/v1/incidents/{video_id}/investigate`` - an agent that chooses its own tools to answer one question.

The agent is the ``investigator`` function of the agent config (a NAT ``tool_calling_agent``); the tools it may choose are
the ``tool_names`` listed there. It writes nothing.

The agent runs through the toolkit's ``SessionManager`` (the only path that writes Phoenix tool spans) under the limits
in :mod:`vss_agents.utils.agent_loop`: 4 iterations, 5 tool steps, 90 s, and a model-call timeout set on its ``llms:``
entry. The response always names how the run ended in ``status`` (HTTP 200), lists every tool that ran in ``steps``, and
lists any ``propose_*`` tool's arguments as ``actions``.

A request may carry the reviewer's unsaved ``draft``. It then runs the ``report_editor`` agent instead, whose tools are
the ``propose_*`` edit checks of :mod:`vss_agents.tools.incident_editor`. Its ``actions`` are the edits the console
applies to the draft; a run with no ``steps`` was not an edit request. For new evidence the editor opens the box tool at
once, from the reviewer's message in ``history``: it asks no question first.

Status codes: 200 with the outcome, 422 for a request that does not validate, 501 when the
profile does not declare the agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.utils import agent_loop
from vss_agents.utils import draft_edits

if TYPE_CHECKING:
    from nat.builder.workflow_builder import WorkflowBuilder

logger = logging.getLogger(__name__)

AGENT_FUNCTION = "investigator"
EDITOR_FUNCTION = "report_editor"

SessionManagerFactory = Callable[[Any, str], Awaitable[Any]]


class HistoryTurn(BaseModel):
    """One earlier chat turn: the reviewer's question or the assistant's answer text, oldest first."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str = Field(..., min_length=1, max_length=4000)


class InvestigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=500)
    draft: draft_edits.DraftSnapshot | None = None
    # The last few chat turns before this question, so "the same item" and follow-ups resolve. Used by the editor only.
    history: list[HistoryTurn] = Field(default_factory=list, max_length=6)


class InvestigateStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any]
    ok: bool
    ms: int
    error: str | None = None


class InvestigateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any]


class InvestigateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="ok, cap_reached, timeout, busy, aborted:<reason> or error")
    answer: str
    steps: list[InvestigateStep]
    actions: list[InvestigateAction]
    wall_ms: int


def _editor_question(question: str, draft: draft_edits.DraftSnapshot, history: list[HistoryTurn]) -> str:
    """The editor agent's input: the request and the draft with each item's key, which the proposal tools name items by.

    It also carries the recent chat turns, so a new-evidence request resolves its second and name from the reviewer's message.
    """
    text = f"{question}\n\nThe draft (name items by their key):\n{draft.model_dump_json(exclude_none=True)}"
    if history:
        earlier = "\n".join(f"{turn.role}: {turn.text}" for turn in history)
        text = f"{text}\n\nThe chat so far, oldest first (resolve 'the same item' and follow-ups from it):\n{earlier}"
    return text


_STOPPED_REASONS = {
    "cap_reached": "The agent reached its tool step limit before it could answer",
    "aborted:step_budget": "The agent reached its tool step limit before it could answer",
    "timeout": "The agent ran out of time before it could answer",
    "busy": "The model is busy, so the agent could not answer",
    "error": "The agent hit an error before it could answer",
}


def _blank_answer_text(status: str, proposed: int) -> str:
    """One plain sentence for a run that ended without a usable answer, saying how many changes it proposed."""
    reason = _STOPPED_REASONS.get(status, "The agent stopped before it could answer")
    if proposed == 0:
        changes = "no changes were proposed"
    elif proposed == 1:
        changes = "1 change was proposed"
    else:
        changes = f"{proposed} changes were proposed"
    return f"{reason}; {changes}."


def create_incident_investigate_router(
    builder: WorkflowBuilder,
    create_session_manager: SessionManagerFactory,
    *,
    agent: str = AGENT_FUNCTION,
    editor: str = EDITOR_FUNCTION,
    wall_seconds: float = agent_loop.WALL_CLOCK_SECONDS,
) -> APIRouter:
    router = APIRouter()
    session_managers: dict[str, Any] = {}
    lock = asyncio.Lock()

    async def _session_manager(name: str) -> Any:
        # One per agent, made on the first request: the config is read when the agent is built, not per call.
        async with lock:
            if name not in session_managers:
                session_managers[name] = await create_session_manager(builder, name)
            return session_managers[name]

    @router.post(
        "/api/v1/incidents/{video_id}/investigate",
        response_model=InvestigateResponse,
        summary="Answer one question about a video with an agent that chooses its tools",
        tags=["Incident Chat"],
    )
    async def investigate(video_id: str, body: InvestigateRequest) -> InvestigateResponse:
        editing = body.draft is not None
        name = editor if editing else agent
        try:
            manager = await _session_manager(name)
        except Exception as exc:
            logger.error("Investigator agent %s is not configured: %s", name, type(exc).__name__)
            raise HTTPException(status_code=501, detail="The investigator is not configured on this profile") from exc
        question = body.question if body.draft is None else _editor_question(body.question, body.draft, body.history)

        async def ask() -> str:
            async with manager.run(question) as runner:
                return str(await runner.result(to_type=str))

        result = await agent_loop.run_loop(ask, video_id, wall_seconds=wall_seconds, draft=body.draft)
        logger.info(
            "Investigated %s: %s in %d ms, %d tool steps", video_id, result.status, result.wall_ms, len(result.steps)
        )
        answer = result.answer
        # NAT's cap text names the agent's internals, so a reviewer gets the plain sentence instead.
        if not answer.strip() or result.status == "cap_reached":
            answer = _blank_answer_text(result.status, len(result.actions))
        return InvestigateResponse(
            status=result.status,
            answer=answer,
            steps=[InvestigateStep(**step) for step in result.steps],
            actions=[InvestigateAction(**action) for action in result.actions],
            wall_ms=result.wall_ms,
        )

    return router


def register_incident_investigate_routes(
    app: FastAPI, builder: WorkflowBuilder, create_session_manager: SessionManagerFactory
) -> None:
    """Register ``POST /api/v1/incidents/{video_id}/investigate`` onto the FastAPI app (always mounted, gated per request)."""
    app.include_router(create_incident_investigate_router(builder, create_session_manager))
    logger.info("Registered POST /api/v1/incidents/{video_id}/investigate")
