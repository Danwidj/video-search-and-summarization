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

from pathlib import Path

import pytest
import yaml

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


async def _run_evidence(*calls: tuple[str, dict]):
    async def ask() -> str:
        for tool, args in calls:
            try:
                await agent_loop.run_guarded_tool(
                    f"propose_{tool}", args, lambda tool=tool, args=args: incident_editor.check_new_evidence(tool, args)
                )
            except ValueError:
                continue
        return "done"

    return await agent_loop.run_loop(ask, "V1", draft=DRAFT)


async def test_the_box_tool_is_listed_as_the_only_action_for_new_evidence() -> None:
    result = await _run_evidence(("open_box_tool", {"seconds": 12, "name": "Bag on floor"}))
    assert result.actions == [{"tool": "propose_open_box_tool", "args": {"seconds": 12, "name": "Bag on floor"}}]


def test_a_question_tool_no_longer_exists_so_no_question_can_be_asked_first() -> None:
    assert not hasattr(incident_editor, "propose_ask_reviewer")
    assert incident_editor.NEW_EVIDENCE_TOOLS == ("open_box_tool",)


async def test_the_box_tool_opens_once_and_only_inside_the_incident() -> None:
    result = await _run_evidence(
        ("open_box_tool", {"seconds": 99, "name": "Bag"}),
        ("open_box_tool", {"seconds": 12, "name": "Bag"}),
        ("open_box_tool", {"seconds": 13, "name": "Bag"}),
    )
    assert result.actions == [{"tool": "propose_open_box_tool", "args": {"seconds": 12, "name": "Bag"}}]
    assert "within the incident" in result.steps[0]["error"]
    assert "already open" in result.steps[2]["error"]


async def test_no_draft_means_no_new_evidence_can_be_proposed() -> None:
    async def ask() -> str:
        await agent_loop.run_guarded_tool(
            "propose_open_box_tool",
            {"seconds": 12, "name": "Bag"},
            lambda: incident_editor.check_new_evidence("open_box_tool", {"seconds": 12, "name": "Bag"}),
        )
        return "done"

    result = await agent_loop.run_loop(ask, "V1", draft=None)
    assert result.actions == []
    assert "no draft" in result.steps[0]["error"]


async def test_a_box_tool_opening_on_a_draft_item_is_listed_by_its_key() -> None:
    result = await _run_evidence(("open_box_tool", {"item_key": "p1"}))
    assert result.actions == [{"tool": "propose_open_box_tool", "args": {"item_key": "p1"}}]


async def test_an_item_key_not_in_the_draft_is_refused() -> None:
    result = await _run_evidence(("open_box_tool", {"item_key": "E1"}))
    assert result.actions == []
    assert "No item with key 'E1'" in result.steps[0]["error"]


async def test_an_item_with_no_seen_second_is_refused() -> None:
    result = await _run_evidence(("open_box_tool", {"item_key": "k1"}))
    assert result.actions == []
    assert "no second it is seen at" in result.steps[0]["error"]


async def test_an_item_opening_cannot_carry_a_second_from_the_model() -> None:
    result = await _run_evidence(("open_box_tool", {"item_key": "p1", "seconds": 3}))
    assert result.actions == []
    assert "item_key alone" in result.steps[0]["error"]


async def test_a_registered_box_tool_logs_the_second_and_the_name() -> None:
    async with incident_editor.propose_open_box_tool(None, None) as info:
        arguments = info.input_schema(seconds=12, name="Bag on floor")

        async def ask() -> str:
            return await info.single_fn(arguments)

        result = await agent_loop.run_loop(ask, "V1", draft=DRAFT)
    assert result.actions == [{"tool": "propose_open_box_tool", "args": {"seconds": 12, "name": "Bag on floor"}}]


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


def test_a_nobody_holder_is_left_out_of_an_upserted_instrument() -> None:
    for nobody in (None, "nobody", " None "):
        assert incident_editor._set_arguments(
            "upsert_instrument", {"op": "add", "name": "knife", "holder_key": nobody}
        ) == {"op": "add", "name": "knife"}
    assert (
        incident_editor._set_arguments("upsert_instrument", {"op": "edit", "item_key": "k1", "holder_key": "p1"})[
            "holder_key"
        ]
        == "p1"
    )


def test_the_report_editor_prompt_opens_the_box_tool_on_an_item_instead_of_refusing() -> None:
    repo = Path(__file__).resolve().parents[5]
    config = repo / "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml"
    prompt = " ".join(yaml.safe_load(config.read_text())["functions"]["report_editor"]["system_prompt"].split())
    assert "I can't do that in chat: re-tracking and images" not in prompt
    assert "call propose_open_box_tool with that item's key alone (no seconds or name)" in prompt
    assert "Never draw or locate a box yourself" in prompt
    assert "I can't do that in chat: there is no such item in the draft." in prompt


def test_the_report_editor_has_no_question_step_for_new_evidence() -> None:
    repo = Path(__file__).resolve().parents[5]
    config = repo / "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml"
    function = yaml.safe_load(config.read_text())["functions"]["report_editor"]
    prompt = " ".join(function["system_prompt"].split())
    assert "propose_ask_reviewer" not in prompt
    assert "propose_ask_reviewer" not in function["tool_names"]
    assert "propose_open_box_tool" in function["tool_names"]
    assert "never ask the reviewer anything about it" in prompt
    assert "Call propose_open_box_tool once, straight away" in prompt
    assert "the incident's start second" in prompt


async def _run_retry(args: dict):
    async def ask() -> str:
        try:
            await agent_loop.run_guarded_tool(
                "propose_retry_gaps", args, lambda: incident_editor.check_retry_gaps("retry_gaps", args)
            )
        except ValueError:
            pass
        return "done"

    return await agent_loop.run_loop(ask, "V1", draft=DRAFT)


async def test_a_gap_retry_of_one_item_or_of_every_gap_is_listed_as_an_action() -> None:
    result = await _run_retry({"item_key": "p1"})
    assert result.actions == [{"tool": "propose_retry_gaps", "args": {"item_key": "p1"}}]
    result = await _run_retry({})
    assert result.actions == [{"tool": "propose_retry_gaps", "args": {}}]


async def test_a_gap_retry_of_an_item_not_in_the_draft_is_an_error_and_no_action() -> None:
    result = await _run_retry({"item_key": "E9"})
    assert result.actions == []
    assert "there is no item E9 in the draft" in result.steps[0]["error"]


def test_a_draft_item_is_named_by_its_label_or_name_in_a_gap_retry() -> None:
    assert incident_editor._item_label(DRAFT, "k1") == "knife"
    assert incident_editor._item_label(DRAFT, "p1") == "p1"
    assert incident_editor._item_label(DRAFT, "E9") is None
