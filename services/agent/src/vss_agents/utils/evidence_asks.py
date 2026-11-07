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

"""Proposal tools for new evidence: at most two questions to the reviewer, then open the box tool.

Nothing here writes or asks anything. The orchestrator sends its calls with the number of questions already asked for
this piece of evidence, and each call is checked here. The console carries out the proposals: ``ask_reviewer`` puts the
question in the report chat, and ``open_box_tool`` opens the box tool at that second with the name filled in, so the
reviewer draws the box. No question may follow the box tool, and the box tool opens once.

Off unless ``INCIDENT_EVIDENCE_ASKS_ENABLED`` is set. See :mod:`vss_agents.api.incident_evidence_asks`.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator

ENABLED_ENV = "INCIDENT_EVIDENCE_ASKS_ENABLED"
MAX_QUESTIONS = 2


def enabled() -> bool:
    """Whether this agent may ask about new evidence. Off unless the setting says otherwise."""
    return (os.environ.get(ENABLED_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


class EvidenceAskError(ValueError):
    """A call the evidence flow cannot take. The message is plain words for the reviewer."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- What the orchestrator sends ----------------------------------------------------------------------------------------


class IncidentWindow(_Strict):
    start_timestamp: float | None = Field(None, ge=0)
    end_timestamp: float | None = Field(None, ge=0)


class AskReviewer(_Strict):
    question: str = Field(min_length=1, max_length=300)


class OpenBoxTool(_Strict):
    seconds: float = Field(ge=0, description="The second the box tool opens at: the best frame to draw on.")
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _name_has_words(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("The name must not be blank.")
        return stripped


# --- Proposals ----------------------------------------------------------------------------------------------------------


class Proposal(_Strict):
    tool: str
    args: dict[str, Any]
    summary: str


class Rejection(_Strict):
    tool: str
    reason: str


class Call(_Strict):
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class ProposalResult(_Strict):
    proposals: list[Proposal] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)


def _check_in_incident(window: IncidentWindow | None, seconds: float) -> None:
    if window is None:
        return
    start, end = window.start_timestamp, window.end_timestamp
    if start is not None and end is not None and not start <= seconds <= end:
        raise EvidenceAskError(f"The box tool must open within the incident, {start:g} to {end:g} seconds.")


def propose(window: IncidentWindow | None, questions_asked: int, calls: list[Call]) -> ProposalResult:
    """Check each call in order. Returns the proposals that pass and why each other call was rejected."""
    result = ProposalResult()
    asked = questions_asked
    opened = False
    for call in calls:
        try:
            if call.tool == "ask_reviewer":
                question = AskReviewer.model_validate(call.args)
                if opened:
                    raise EvidenceAskError("The box tool is already open; no more questions for this evidence.")
                if asked >= MAX_QUESTIONS:
                    raise EvidenceAskError(
                        f"Only {MAX_QUESTIONS} questions are allowed for one piece of evidence; open the box tool."
                    )
                asked += 1
                result.proposals.append(
                    Proposal(tool="ask_reviewer", args=question.model_dump(), summary="Ask the reviewer a question")
                )
            elif call.tool == "open_box_tool":
                args = OpenBoxTool.model_validate(call.args)
                if opened:
                    raise EvidenceAskError("The box tool is already open for this evidence.")
                _check_in_incident(window, args.seconds)
                opened = True
                result.proposals.append(
                    Proposal(
                        tool="open_box_tool",
                        args=args.model_dump(),
                        summary=f"Open the box tool at {args.seconds:g} seconds as {args.name}",
                    )
                )
            else:
                result.rejected.append(Rejection(tool=call.tool, reason=f"There is no tool called {call.tool!r}."))
        except EvidenceAskError as exc:
            result.rejected.append(Rejection(tool=call.tool, reason=str(exc)))
        except ValidationError as exc:
            reason = "; ".join(str(error["msg"]).removeprefix("Value error, ") for error in exc.errors())
            result.rejected.append(Rejection(tool=call.tool, reason=reason))
    return result
