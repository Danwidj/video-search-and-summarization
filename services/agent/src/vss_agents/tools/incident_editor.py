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

One tool per entry of :data:`vss_agents.utils.draft_edits.TOOLS`, named ``propose_<tool>``. Each checks the model's
arguments against the reviewer's draft, which the route binds to the run (``agent_loop.current().draft``), and returns
the proposal's summary. A rejected edit goes back to the model as the tool's error text so it can fix the call. Nothing
is written: the route lists the arguments of every ``propose_*`` step as ``actions``, and the console applies them.
"""

from collections.abc import AsyncGenerator
from typing import Any

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from vss_agents.utils import agent_loop
from vss_agents.utils import draft_edits


async def propose(tool: str, args: dict[str, Any]) -> str:
    """Check one edit against the run's draft and return its summary; a rejected edit is a ``ValueError``."""
    draft = agent_loop.current().draft
    if draft is None:
        raise ValueError("there is no draft to edit")
    result = draft_edits.propose(draft, [draft_edits.Call(tool=tool, args=args)])
    if result.rejected:
        raise ValueError(result.rejected[0].reason)
    return result.proposals[0].summary


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


def _register(tool: str, config_type: type[FunctionBaseConfig]) -> Any:
    spec = draft_edits.TOOLS[tool]
    name = f"{agent_loop.PROPOSAL_PREFIX}{tool}"

    async def build(config: FunctionBaseConfig, builder: Builder) -> AsyncGenerator[FunctionInfo]:  # noqa: ARG001
        async def run(arguments: Any) -> str:
            args = _set_arguments(tool, arguments.model_dump())
            return await agent_loop.run_guarded_tool(name, args, lambda: propose(tool, args))

        # The toolkit checks the argument's annotation, so it must be the model class, not Any.
        run.__annotations__["arguments"] = spec.args_model
        yield FunctionInfo.create(
            single_fn=run,
            description=f"{spec.description} Proposes only; the reviewer's page applies it.",
            input_schema=spec.args_model,
            single_output_schema=str,
        )

    return register_function(config_type=config_type, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])(build)


propose_set_incident_fields = _register("set_incident_fields", ProposeSetIncidentFieldsConfig)
propose_set_timeline_item = _register("set_timeline_item", ProposeSetTimelineItemConfig)
propose_upsert_entity = _register("upsert_entity", ProposeUpsertEntityConfig)
propose_upsert_instrument = _register("upsert_instrument", ProposeUpsertInstrumentConfig)
propose_upsert_asset = _register("upsert_asset", ProposeUpsertAssetConfig)
propose_set_instrument_holder = _register("set_instrument_holder", ProposeSetInstrumentHolderConfig)
propose_delete_item = _register("delete_item", ProposeDeleteItemConfig)
