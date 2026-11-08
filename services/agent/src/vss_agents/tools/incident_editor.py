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

"""Proposal tools for the report editor agent (``POST /api/v1/incidents/{video_id}/investigate`` with a ``draft``).

One tool per entry of :data:`vss_agents.utils.draft_edits.TOOLS`, named ``propose_<tool>``, and two for new evidence:
``propose_ask_reviewer`` and ``propose_open_box_tool`` (checked by :mod:`vss_agents.utils.evidence_asks`). Each checks the
model's arguments against the reviewer's draft, which the route binds to the run (``agent_loop.current().draft``), and
returns the proposal's summary. A rejected edit goes back to the model as the tool's error text so it can fix the call.
Nothing is written: the route lists the arguments of every ``propose_*`` step as ``actions``, and the console applies them.
"""

from collections.abc import AsyncGenerator
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel
from pydantic import Field

from vss_agents.utils import agent_loop
from vss_agents.utils import draft_edits
from vss_agents.utils import evidence_asks

Check = Callable[[str, dict[str, Any]], Awaitable[str]]
NEW_EVIDENCE_TOOLS = ("ask_reviewer", "open_box_tool")


async def propose(tool: str, args: dict[str, Any]) -> str:
    """Check one edit against the run's draft and return its summary; a rejected edit is a ``ValueError``."""
    draft = agent_loop.current().draft
    if draft is None:
        raise ValueError("there is no draft to edit")
    result = draft_edits.propose(draft, [draft_edits.Call(tool=tool, args=args)])
    if result.rejected:
        raise ValueError(result.rejected[0].reason)
    return result.proposals[0].summary


def _seen_seconds(draft: draft_edits.DraftSnapshot) -> dict[str, float | None]:
    """Each draft item's key and the second it is seen at: an entity's first sight, else its timestamp."""
    seen: dict[str, float | None] = {}
    for entity in draft.entities:
        seen[entity.key] = (
            entity.first_seen_seconds if entity.first_seen_seconds is not None else entity.timestamp_seconds
        )
    seen.update({instrument.key: instrument.timestamp_seconds for instrument in draft.instruments})
    seen.update({asset.key: asset.timestamp_seconds for asset in draft.assets})
    return seen


async def check_new_evidence(tool: str, args: dict[str, Any]) -> str:
    """Check one new-evidence call against the incident window, the draft's items, the questions already asked and this run's
    earlier calls.

    A rejected call is a ``ValueError``. The earlier calls are the ones that passed in this run, from the step log.
    """
    run = agent_loop.current()
    if run.draft is None:
        raise ValueError("there is no draft to change")
    earlier = [
        evidence_asks.Call(tool=step["tool"].removeprefix(agent_loop.PROPOSAL_PREFIX), args=step["args"])
        for step in run.steps
        if step["ok"] and step["tool"].removeprefix(agent_loop.PROPOSAL_PREFIX) in NEW_EVIDENCE_TOOLS
    ]
    incident = run.draft.incident
    window = evidence_asks.IncidentWindow(
        start_timestamp=incident.start_timestamp, end_timestamp=incident.end_timestamp
    )
    result = evidence_asks.propose(
        window,
        run.questions_asked,
        [*earlier, evidence_asks.Call(tool=tool, args=args)],
        items=_seen_seconds(run.draft),
    )
    if result.rejected:
        raise ValueError(result.rejected[-1].reason)
    return result.proposals[-1].summary


class ProposeSetIncidentFieldsConfig(FunctionBaseConfig, name="propose_set_incident_fields"):
    pass


class ProposeSetTimelineItemConfig(FunctionBaseConfig, name="propose_set_timeline_item"):
    pass


class ProposeUpsertEntityConfig(FunctionBaseConfig, name="propose_upsert_entity"):
    pass


class ProposeUpsertInstrumentConfig(FunctionBaseConfig, name="propose_upsert_instrument"):
    pass


class ProposeUpsertAssetConfig(FunctionBaseConfig, name="propose_upsert_asset"):
    pass


class ProposeSetInstrumentHolderConfig(FunctionBaseConfig, name="propose_set_instrument_holder"):
    pass


class ProposeDeleteItemConfig(FunctionBaseConfig, name="propose_delete_item"):
    pass


class ProposeAskReviewerConfig(FunctionBaseConfig, name="propose_ask_reviewer"):
    pass


class ProposeOpenBoxToolConfig(FunctionBaseConfig, name="propose_open_box_tool"):
    pass


class ProposeRetryGapsConfig(FunctionBaseConfig, name="propose_retry_gaps"):
    pass


class RetryGaps(BaseModel):
    """Which items to look again for in the video."""

    item_key: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description="The draft item to look again for, by its key. Left out, every item of the report with no box.",
    )


_NOBODY = {"", "none", "null", "nobody"}


def _set_arguments(tool: str, dumped: dict[str, Any]) -> dict[str, Any]:
    """What the model set. It fills every field of the schema, with null for the ones it means to leave out."""
    args = {key: value for key, value in dumped.items() if value is not None}
    if tool == "set_instrument_holder":
        # A holder of null means nobody, so it stays; a model often writes the word instead of a null.
        holder = dumped.get("holder_key")
        args["holder_key"] = None if holder is None or str(holder).strip().lower() in _NOBODY else holder
    elif tool == "upsert_instrument" and str(args.get("holder_key", "")).strip().lower() in _NOBODY:
        # Nobody is the default for an added instrument, and an edit keeps its holder; set_instrument_holder clears one.
        args.pop("holder_key", None)
    return args


def _proposal(
    config_type: type[FunctionBaseConfig], tool: str, args_model: type[BaseModel], description: str, check: Check
) -> Any:
    name = f"{agent_loop.PROPOSAL_PREFIX}{tool}"

    async def build(config: FunctionBaseConfig, builder: Builder) -> AsyncGenerator[FunctionInfo]:  # noqa: ARG001
        async def run(arguments: Any) -> str:
            args = _set_arguments(tool, arguments.model_dump())
            return await agent_loop.run_guarded_tool(name, args, lambda: check(tool, args))

        # The toolkit checks the argument's annotation, so it must be the model class, not Any.
        run.__annotations__["arguments"] = args_model
        yield FunctionInfo.create(
            single_fn=run,
            description=description,
            input_schema=args_model,
            single_output_schema=str,
        )

    return register_function(config_type=config_type, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])(build)


def _item_label(draft: draft_edits.DraftSnapshot, key: str) -> str | None:
    """The label a reviewer knows a draft item by (its label, else its name), or None when the draft has no such item."""
    items: list[draft_edits.DraftEntity | draft_edits.DraftInstrument | draft_edits.DraftAsset] = [
        *draft.entities,
        *draft.instruments,
        *draft.assets,
    ]
    for item in items:
        if item.key == key:
            return item.label or getattr(item, "name", "") or key
    return None


async def check_retry_gaps(tool: str, args: dict[str, Any]) -> str:  # noqa: ARG001
    """Check a gap retry request: the named item must be in the draft. The retry itself runs as a job the console starts."""
    draft = agent_loop.current().draft
    if draft is None:
        raise ValueError("there is no draft to change")
    key = args.get("item_key")
    if key is None:
        return "Retrying the gaps of the report: each box found comes back as a proposal for the reviewer to confirm."
    label = _item_label(draft, key)
    if label is None:
        raise ValueError(f"there is no item {key} in the draft")
    return f"Retrying the gap of {label}: its box comes back as a proposal for the reviewer to confirm."


def _register(tool: str, config_type: type[FunctionBaseConfig]) -> Any:
    spec = draft_edits.TOOLS[tool]
    return _proposal(
        config_type,
        tool,
        spec.args_model,
        f"{spec.description} Proposes only; the reviewer's page applies it.",
        propose,
    )


propose_set_incident_fields = _register("set_incident_fields", ProposeSetIncidentFieldsConfig)
propose_set_timeline_item = _register("set_timeline_item", ProposeSetTimelineItemConfig)
propose_upsert_entity = _register("upsert_entity", ProposeUpsertEntityConfig)
propose_upsert_instrument = _register("upsert_instrument", ProposeUpsertInstrumentConfig)
propose_upsert_asset = _register("upsert_asset", ProposeUpsertAssetConfig)
propose_set_instrument_holder = _register("set_instrument_holder", ProposeSetInstrumentHolderConfig)
propose_delete_item = _register("delete_item", ProposeDeleteItemConfig)
propose_ask_reviewer = _proposal(
    ProposeAskReviewerConfig,
    "ask_reviewer",
    evidence_asks.AskReviewer,
    "Asks the reviewer one short question about new evidence, at most two in all. Proposes only; the report chat shows it.",
    check_new_evidence,
)
propose_open_box_tool = _proposal(
    ProposeOpenBoxToolConfig,
    "open_box_tool",
    evidence_asks.OpenBoxTool,
    "Opens the box tool once: for new evidence at the second it is best seen, with its short name; or on an item already in "
    "the draft, by its item_key alone, to redraw its box or set its image. Proposes only; the reviewer draws the box.",
    check_new_evidence,
)
propose_retry_gaps = _proposal(
    ProposeRetryGapsConfig,
    "retry_gaps",
    RetryGaps,
    "Looks again in the video for the items of the saved report that have no box: all of them, or the one named by its "
    "item_key. Each box found comes back as a proposal the reviewer confirms or adjusts; nothing is written. Use it when "
    "asked to retry the gaps, or to find a box for an item.",
    check_retry_gaps,
)
