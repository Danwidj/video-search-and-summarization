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

"""Proposal tools for the report editor: each checks one edit against the supplied draft and proposes it.

Nothing here writes. The draft is the reviewer's unsaved draft, sent as a snapshot with each request. Tools name items by
their draft ``key`` (stable in the browser), never by the ``E#``/``I#``/``A#`` ids, which are renumbered on send, so an
invented or renumbered id is rejected as an unknown key. Seconds must lie inside the incident window when it is set.

The proposals are applied by the console (see the scout report, ``data/vss-agent-chat-editor/report.md``). See :mod:`vss_agents.api.incident_draft_edits`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import model_validator

if TYPE_CHECKING:
    from collections.abc import Callable

INCIDENT_TYPES = ("road accident", "burglary", "explosion", "assault", "animal attack")
ENTITY_TYPES = ("human", "animal")
SEVERITY_MAX = 5
THREAT_MAX = 5

# Rule for the planner prompt that answers an off-topic request by refusing rather than answering from its own knowledge
# (scout case E6). The planner, not this module, owns the prompt; this text is for it to include.
OUT_OF_SCOPE_RULE = (
    "If the request is not an edit to this incident report, call no tool and say you can only edit the report. "
    "Never answer it from your own knowledge."
)


class DraftEditError(ValueError):
    """An edit the draft cannot take. The message is plain words for the reviewer."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- The draft snapshot the console sends -------------------------------------------------------------------------------


class DraftIncident(_Strict):
    type: str | None = None
    title: str = ""
    start_timestamp: float | None = Field(None, ge=0)
    end_timestamp: float | None = Field(None, ge=0)
    description: str = ""
    severity_level: int | None = Field(None, ge=1, le=SEVERITY_MAX)
    severity_reason: str = ""


class DraftEntity(_Strict):
    key: str = Field(min_length=1, max_length=128)
    type: str = "unknown"
    description: str = ""
    first_seen_seconds: float | None = Field(None, ge=0)
    last_seen_seconds: float | None = Field(None, ge=0)
    timestamp_seconds: float | None = Field(None, ge=0)
    label: str = ""
    # What the reviewer sees for the item: E1/I1/A1 and its name. Optional, so a console that does not send them still works.
    reviewer_label: str = ""
    reviewer_name: str = ""


class DraftInstrument(_Strict):
    key: str = Field(min_length=1, max_length=128)
    holder_key: str | None = None
    name: str = ""
    description: str = ""
    threat_level: int | None = Field(None, ge=1, le=THREAT_MAX)
    timestamp_seconds: float | None = Field(None, ge=0)
    label: str = ""
    reviewer_label: str = ""
    reviewer_name: str = ""


class DraftAsset(_Strict):
    key: str = Field(min_length=1, max_length=128)
    name: str = ""
    description: str = ""
    timestamp_seconds: float | None = Field(None, ge=0)
    label: str = ""
    reviewer_label: str = ""
    reviewer_name: str = ""


class DraftSnapshot(_Strict):
    incident: DraftIncident
    entities: list[DraftEntity] = Field(default_factory=list)
    instruments: list[DraftInstrument] = Field(default_factory=list)
    assets: list[DraftAsset] = Field(default_factory=list)

    @model_validator(mode="after")
    def _keys_unique(self) -> DraftSnapshot:
        keys = (
            [item.key for item in self.entities]
            + [item.key for item in self.instruments]
            + [item.key for item in self.assets]
        )
        if len(keys) != len(set(keys)):
            raise ValueError("draft item keys must be unique")
        return self


# --- Tool arguments and proposals ---------------------------------------------------------------------------------------


class SetIncidentFields(_Strict):
    type: Literal["road accident", "burglary", "explosion", "assault", "animal attack"] | None = None
    title: str | None = Field(None, min_length=1)
    description: str | None = None
    severity_level: int | None = Field(None, ge=1, le=SEVERITY_MAX)
    severity_reason: str | None = None
    start_timestamp: float | None = Field(None, ge=0)
    end_timestamp: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _something_to_set(self) -> SetIncidentFields:
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("name at least one incident field to set")
        return self


class SetTimelineItem(_Strict):
    item_key: str = Field(min_length=1)
    timestamp_seconds: float | None = Field(None, ge=0)
    label: str | None = None

    @model_validator(mode="after")
    def _something_to_set(self) -> SetTimelineItem:
        if self.timestamp_seconds is None and self.label is None:
            raise ValueError("give a timestamp_seconds or a label")
        return self


class UpsertEntity(_Strict):
    op: Literal["add", "edit"]
    item_key: str | None = Field(None, min_length=1)
    entity_type: Literal["human", "animal"] | None = None
    name: str | None = None
    description: str | None = None
    first_seen_seconds: float | None = Field(None, ge=0)
    last_seen_seconds: float | None = Field(None, ge=0)
    timestamp_seconds: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> UpsertEntity:
        if self.op == "add":
            if self.item_key is not None:
                raise ValueError("an added entity takes no item_key")
            if not self.name or None in (self.entity_type, self.first_seen_seconds, self.last_seen_seconds):
                raise ValueError("an added entity needs a name, entity_type, first_seen_seconds and last_seen_seconds")
        elif self.item_key is None:
            raise ValueError("editing an entity needs its item_key")
        return self


class UpsertInstrument(_Strict):
    op: Literal["add", "edit"]
    item_key: str | None = Field(None, min_length=1)
    name: str | None = None
    description: str | None = None
    threat_level: int | None = Field(None, ge=1, le=THREAT_MAX)
    holder_key: str | None = Field(None, min_length=1)
    timestamp_seconds: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> UpsertInstrument:
        if self.op == "add":
            if self.item_key is not None:
                raise ValueError("an added instrument takes no item_key")
            if not self.name or self.threat_level is None:
                raise ValueError("an added instrument needs a name and a threat_level (1-5)")
        elif self.item_key is None:
            raise ValueError("editing an instrument needs its item_key")
        return self


class UpsertAsset(_Strict):
    op: Literal["add", "edit"]
    item_key: str | None = Field(None, min_length=1)
    name: str | None = None
    description: str | None = None
    timestamp_seconds: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> UpsertAsset:
        if self.op == "add":
            if self.item_key is not None:
                raise ValueError("an added asset takes no item_key")
            if not self.name:
                raise ValueError("an added asset needs a name")
        elif self.item_key is None:
            raise ValueError("editing an asset needs its item_key")
        return self


class SetInstrumentHolder(_Strict):
    instrument_key: str = Field(min_length=1)
    holder_key: str | None = Field(min_length=1)


class DeleteItem(_Strict):
    item_key: str = Field(min_length=1)


class Proposal(_Strict):
    tool: str
    args: dict[str, Any]
    summary: str
    also_removes: list[str] = Field(
        default_factory=list, description="Other item keys the console removes with this one"
    )


# --- Checks shared by the tools -----------------------------------------------------------------------------------------


def _find(draft: DraftSnapshot, key: str, collection: str) -> Any:
    pools: dict[str, list[Any]] = {"entity": draft.entities, "instrument": draft.instruments, "asset": draft.assets}
    items = pools[collection]
    for item in items:
        if item.key == key:
            return item
    raise DraftEditError(f"No {collection} with key {key!r} in the draft.")


def _find_any(draft: DraftSnapshot, key: str) -> tuple[str, Any]:
    for collection in ("entity", "instrument", "asset"):
        try:
            return collection, _find(draft, key, collection)
        except DraftEditError:
            continue
    raise DraftEditError(f"No item with key {key!r} in the draft.")


def _check_in_incident(draft: DraftSnapshot, seconds: float | None, what: str) -> None:
    if seconds is None:
        return
    start, end = draft.incident.start_timestamp, draft.incident.end_timestamp
    if start is not None and end is not None and not start <= seconds <= end:
        raise DraftEditError(f"{what} must lie within the incident, {start:g} to {end:g} seconds.")


def _check_span(first: float | None, last: float | None) -> None:
    if first is not None and last is not None and last < first:
        raise DraftEditError("An entity's last seen must not be before its first seen.")


# --- The tools ----------------------------------------------------------------------------------------------------------


def _set_incident_fields(draft: DraftSnapshot, args: SetIncidentFields) -> Proposal:
    start = args.start_timestamp if args.start_timestamp is not None else draft.incident.start_timestamp
    end = args.end_timestamp if args.end_timestamp is not None else draft.incident.end_timestamp
    if start is not None and end is not None and end < start:
        raise DraftEditError("The incident end must not be before its start.")
    changes = args.model_dump(exclude_none=True)
    return Proposal(tool="set_incident_fields", args=changes, summary=f"Set {', '.join(changes)}")


def _set_timeline_item(draft: DraftSnapshot, args: SetTimelineItem) -> Proposal:
    collection, item = _find_any(draft, args.item_key)
    if args.timestamp_seconds is not None:
        _check_in_incident(draft, args.timestamp_seconds, "The timestamp")
        if collection == "entity":
            first = item.first_seen_seconds
            last = item.last_seen_seconds
            if first is not None and last is not None and not first <= args.timestamp_seconds <= last:
                raise DraftEditError("The timestamp must lie within the entity's first to last seen.")
    return Proposal(
        tool="set_timeline_item",
        args=args.model_dump(exclude_none=True),
        summary=f"Set the timeline of {args.item_key}",
    )


def _upsert_entity(draft: DraftSnapshot, args: UpsertEntity) -> Proposal:
    if args.op == "add":
        first, last = args.first_seen_seconds, args.last_seen_seconds
        current_first: float | None = first
        current_last: float | None = last
    else:
        entity = _find(draft, args.item_key or "", "entity")
        current_first = args.first_seen_seconds if args.first_seen_seconds is not None else entity.first_seen_seconds
        current_last = args.last_seen_seconds if args.last_seen_seconds is not None else entity.last_seen_seconds
    _check_in_incident(draft, args.first_seen_seconds, "The first seen second")
    _check_in_incident(draft, args.last_seen_seconds, "The last seen second")
    _check_span(current_first, current_last)
    if (
        args.timestamp_seconds is not None
        and current_first is not None
        and current_last is not None
        and not current_first <= args.timestamp_seconds <= current_last
    ):
        raise DraftEditError("The timestamp must lie within the entity's first to last seen.")
    verb = "Add a person or animal" if args.op == "add" else f"Edit {args.item_key}"
    return Proposal(tool="upsert_entity", args=args.model_dump(exclude_none=True), summary=verb)


def _upsert_instrument(draft: DraftSnapshot, args: UpsertInstrument) -> Proposal:
    if args.op == "edit":
        _find(draft, args.item_key or "", "instrument")
    if args.holder_key is not None:
        _find(draft, args.holder_key, "entity")
    _check_in_incident(draft, args.timestamp_seconds, "The timestamp")
    verb = f"Add instrument {args.name}" if args.op == "add" else f"Edit {args.item_key}"
    if args.holder_key is not None:
        verb += f", held by {args.holder_key}"
    return Proposal(tool="upsert_instrument", args=args.model_dump(exclude_none=True), summary=verb)


def _upsert_asset(draft: DraftSnapshot, args: UpsertAsset) -> Proposal:
    if args.op == "edit":
        _find(draft, args.item_key or "", "asset")
    _check_in_incident(draft, args.timestamp_seconds, "The timestamp")
    verb = f"Add asset {args.name}" if args.op == "add" else f"Edit {args.item_key}"
    return Proposal(tool="upsert_asset", args=args.model_dump(exclude_none=True), summary=verb)


def _set_instrument_holder(draft: DraftSnapshot, args: SetInstrumentHolder) -> Proposal:
    _find(draft, args.instrument_key, "instrument")
    if args.holder_key is not None:
        _find(draft, args.holder_key, "entity")
    holder = "nobody" if args.holder_key is None else args.holder_key
    return Proposal(
        tool="set_instrument_holder",
        args=args.model_dump(),
        summary=f"Set the holder of {args.instrument_key} to {holder}",
    )


def _delete_item(draft: DraftSnapshot, args: DeleteItem) -> Proposal:
    collection, _ = _find_any(draft, args.item_key)
    also = []
    if collection == "entity":
        also = [instrument.key for instrument in draft.instruments if instrument.holder_key == args.item_key]
    summary = f"Delete {args.item_key}"
    if also:
        summary += f", and the {len(also)} instrument(s) it holds"
    return Proposal(tool="delete_item", args=args.model_dump(), summary=summary, also_removes=also)


@dataclass(frozen=True)
class Tool:
    """A proposal tool: its argument model and the check that turns arguments into a proposal."""

    args_model: type[BaseModel]
    propose: Callable[[DraftSnapshot, Any], Proposal]
    description: str


TOOLS: dict[str, Tool] = {
    "set_incident_fields": Tool(
        args_model=SetIncidentFields,
        propose=_set_incident_fields,
        description="Set any of the incident's type, title, description, severity, or start and end seconds.",
    ),
    "set_timeline_item": Tool(
        args_model=SetTimelineItem,
        propose=_set_timeline_item,
        description="Set the timestamp or label of an entity, instrument or asset, by its draft key.",
    ),
    "upsert_entity": Tool(
        args_model=UpsertEntity,
        propose=_upsert_entity,
        description="Add a person or animal (with a short name), or edit one, by draft key.",
    ),
    "upsert_instrument": Tool(
        args_model=UpsertInstrument,
        propose=_upsert_instrument,
        description="Add an instrument (object or weapon, threat 1-5), or edit one, by draft key.",
    ),
    "upsert_asset": Tool(
        args_model=UpsertAsset,
        propose=_upsert_asset,
        description="Add an asset, or edit one, by draft key.",
    ),
    "set_instrument_holder": Tool(
        args_model=SetInstrumentHolder,
        propose=_set_instrument_holder,
        description="Set which entity holds an instrument, by draft keys; a null holder means nobody.",
    ),
    "delete_item": Tool(
        args_model=DeleteItem,
        propose=_delete_item,
        description="Delete an entity, instrument or asset by draft key; an entity's instruments are removed with it.",
    ),
}


class Rejection(_Strict):
    tool: str
    reason: str


class Call(_Strict):
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class ProposalResult(_Strict):
    proposals: list[Proposal] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)


def propose(draft: DraftSnapshot, calls: list[Call]) -> ProposalResult:
    """Check each call against the draft. Returns the proposals that pass and why each other call was rejected."""
    result = ProposalResult()
    for call in calls:
        tool = TOOLS.get(call.tool)
        if tool is None:
            result.rejected.append(Rejection(tool=call.tool, reason=f"There is no tool called {call.tool!r}."))
            continue
        try:
            args = tool.args_model.model_validate(call.args)
            result.proposals.append(tool.propose(draft, args))
        except DraftEditError as exc:
            result.rejected.append(Rejection(tool=call.tool, reason=str(exc)))
        except ValidationError as exc:
            reason = "; ".join(str(error["msg"]).removeprefix("Value error, ") for error in exc.errors())
            result.rejected.append(Rejection(tool=call.tool, reason=reason))
    return result
