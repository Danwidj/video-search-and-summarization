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

"""Proposal checks for new evidence: the box tool opens at once, with no question to the reviewer first.

Nothing here writes or asks anything. The report editor's ``propose_open_box_tool`` tool
(:mod:`vss_agents.tools.incident_editor`) and the ``evidence-asks`` route (:mod:`vss_agents.api.incident_evidence_asks`)
check each call here. The console carries out the proposal: ``open_box_tool`` opens the box tool at that second with the
name filled in, so the reviewer draws the box. With an ``item_key`` it opens the box tool on that draft item at its own
seen second, to redraw its box or set its image. The box tool opens once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from pydantic import model_validator

if TYPE_CHECKING:
    from collections.abc import Mapping


class EvidenceAskError(ValueError):
    """A call the evidence flow cannot take. The message is plain words for the reviewer."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- What the orchestrator sends ----------------------------------------------------------------------------------------


class IncidentWindow(_Strict):
    start_timestamp: float | None = Field(None, ge=0)
    end_timestamp: float | None = Field(None, ge=0)


class OpenBoxTool(_Strict):
    """New evidence (``seconds`` and ``name``), or an existing draft item (``item_key`` alone, to redraw its box)."""

    item_key: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description="An item already in the draft: the box tool opens on it at its own seen second, to redraw its box.",
    )
    seconds: float | None = Field(
        None, ge=0, description="New evidence: the second the box tool opens at, the best frame to draw on."
    )
    name: str | None = Field(None, max_length=80, description="New evidence: a short name for it.")

    @model_validator(mode="after")
    def _shape(self) -> OpenBoxTool:
        if self.item_key is not None:
            if self.seconds is not None or self.name is not None:
                raise ValueError("An existing item opens at its own second: give its item_key alone.")
        elif self.seconds is None or self.name is None:
            raise ValueError("New evidence needs its seconds and a name.")
        return self

    @field_validator("name")
    @classmethod
    def _name_has_words(cls, value: str | None) -> str | None:
        if value is None:
            return None
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


def _item_seconds(items: Mapping[str, float | None] | None, key: str) -> None:
    """An existing draft item the box tool can open on: it must be in the draft and have a second it is seen at."""
    if items is None or key not in items:
        raise EvidenceAskError(f"No item with key {key!r} in the draft.")
    if items[key] is None:
        raise EvidenceAskError(f"{key} has no second it is seen at, so the box tool cannot open on it.")


def propose(
    window: IncidentWindow | None,
    calls: list[Call],
    items: Mapping[str, float | None] | None = None,
) -> ProposalResult:
    """Check each call in order. Returns the proposals that pass and why each other call was rejected.

    ``items`` maps each draft item's key to the second it is seen at (None when it has none); ``None`` means no draft.
    """
    result = ProposalResult()
    opened = False
    for call in calls:
        try:
            if call.tool == "open_box_tool":
                args = OpenBoxTool.model_validate(call.args)
                if opened:
                    raise EvidenceAskError("The box tool is already open for this evidence.")
                if args.item_key is not None:
                    _item_seconds(items, args.item_key)
                    summary = f"Open the box tool on {args.item_key} to redraw its box"
                else:
                    if args.seconds is None or args.name is None:  # the model validator makes this unreachable
                        raise EvidenceAskError("New evidence needs its seconds and a name.")
                    _check_in_incident(window, args.seconds)
                    summary = f"Open the box tool at {args.seconds:g} seconds as {args.name}"
                opened = True
                result.proposals.append(
                    Proposal(tool="open_box_tool", args=args.model_dump(exclude_none=True), summary=summary)
                )
            else:
                result.rejected.append(Rejection(tool=call.tool, reason=f"There is no tool called {call.tool!r}."))
        except EvidenceAskError as exc:
            result.rejected.append(Rejection(tool=call.tool, reason=str(exc)))
        except ValidationError as exc:
            reason = "; ".join(str(error["msg"]).removeprefix("Value error, ") for error in exc.errors())
            result.rejected.append(Rejection(tool=call.tool, reason=reason))
    return result
