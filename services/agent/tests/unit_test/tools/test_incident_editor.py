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

"""Unit tests for the report editor's proposal tools (no model, no network)."""

import pytest

from vss_agents.tools import incident_editor
from vss_agents.utils import agent_loop
from vss_agents.utils import draft_edits

pytestmark = pytest.mark.asyncio

DRAFT = draft_edits.DraftSnapshot.model_validate(
    {
        "incident": {"type": "assault", "title": "Fight", "start_timestamp": 0, "end_timestamp": 30},
        "entities": [{"key": "p1", "type": "human", "first_seen_seconds": 1, "last_seen_seconds": 20}],
        "instruments": [{"key": "k1", "name": "knife", "threat_level": 3, "holder_key": "p1"}],
        "assets": [],
    }
)


async def _run(*calls: tuple[str, dict], draft=DRAFT):
    async def ask() -> str:
        for tool, args in calls:
            try:
                await agent_loop.run_guarded_tool(
                    f"propose_{tool}", args, lambda tool=tool, args=args: incident_editor.propose(tool, args)
                )
            except ValueError:
                continue
        return "done"

    return await agent_loop.run_loop(ask, "V1", draft=draft)


async def test_a_valid_edit_is_listed_as_an_action() -> None:
    result = await _run(("set_incident_fields", {"severity_level": 4}))
    assert result.status == "ok"
    assert result.actions == [{"tool": "propose_set_incident_fields", "args": {"severity_level": 4}}]


async def test_an_invented_key_is_an_error_the_model_reads_and_no_action() -> None:
    result = await _run(("delete_item", {"item_key": "E1"}))
    assert result.actions == []
    assert result.steps[0]["ok"] is False
    assert "No item with key 'E1'" in result.steps[0]["error"]


async def test_an_edit_outside_the_incident_window_is_rejected() -> None:
    result = await _run(("set_timeline_item", {"item_key": "p1", "timestamp_seconds": 99}))
    assert result.actions == []
    assert "within the incident" in result.steps[0]["error"]


async def test_no_draft_means_nothing_can_be_proposed() -> None:
    result = await _run(("set_incident_fields", {"severity_level": 4}), draft=None)
    assert result.actions == []
    assert "no draft" in result.steps[0]["error"]


async def test_the_tool_is_checked_by_the_same_rules_as_the_draft_edits_route() -> None:
    summary = await _with_draft(lambda: incident_editor.propose("delete_item", {"item_key": "p1"}))
    assert "the 1 instrument(s) it holds" in summary


async def _with_draft(call):
    out: list[str] = []

    async def ask() -> str:
        out.append(await call())
        return "done"

    await agent_loop.run_loop(ask, "V1", draft=DRAFT)
    return out[0]


async def test_a_registered_tool_logs_the_arguments_the_model_set() -> None:
    async with incident_editor.propose_set_instrument_holder(None, None) as info:
        arguments = info.input_schema(instrument_key="k1", holder_key=None)

        async def ask() -> str:
            return await info.single_fn(arguments)

        result = await agent_loop.run_loop(ask, "V1", draft=DRAFT)
    assert result.actions == [
        {"tool": "propose_set_instrument_holder", "args": {"instrument_key": "k1", "holder_key": None}}
    ]


def test_nulls_the_model_filled_in_are_left_out_but_a_holder_of_nobody_stays() -> None:
    assert incident_editor._set_arguments("set_incident_fields", {"title": None, "severity_level": 4}) == {
        "severity_level": 4
    }
    for nobody in (None, "None", " null "):
        assert incident_editor._set_arguments(
            "set_instrument_holder", {"instrument_key": "k1", "holder_key": nobody}
        ) == {"instrument_key": "k1", "holder_key": None}
    assert (
        incident_editor._set_arguments("set_instrument_holder", {"instrument_key": "k1", "holder_key": "p1"})[
            "holder_key"
        ]
        == "p1"
    )
