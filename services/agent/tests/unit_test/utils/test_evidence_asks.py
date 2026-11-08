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

"""Unit tests for the new-evidence rules: one box tool opening, and no question step before it (2026-11-09)."""

from vss_agents.utils import evidence_asks as ea

WINDOW = ea.IncidentWindow(start_timestamp=10, end_timestamp=60)


def open_box(seconds: float = 24, name: str = "Red hood") -> ea.Call:
    return ea.Call(tool="open_box_tool", args={"seconds": seconds, "name": name})


def test_the_box_tool_opens_at_once_with_no_question_step() -> None:
    result = ea.propose(WINDOW, [open_box(30, "Red hood")])
    assert [p.tool for p in result.proposals] == ["open_box_tool"]
    assert result.proposals[0].args == {"seconds": 30, "name": "Red hood"}
    assert result.rejected == []


def test_the_question_tool_is_gone_so_a_call_to_it_is_rejected() -> None:
    result = ea.propose(WINDOW, [ea.Call(tool="ask_reviewer", args={"question": "Who is in the red hood?"})])
    assert result.proposals == []
    assert result.rejected[0].reason == "There is no tool called 'ask_reviewer'."


def test_a_question_before_the_box_tool_is_rejected_and_the_box_tool_still_opens() -> None:
    result = ea.propose(
        WINDOW,
        [ea.Call(tool="ask_reviewer", args={"question": "Where?"}), open_box(30, "Red hood")],
    )
    assert [p.tool for p in result.proposals] == ["open_box_tool"]
    assert [r.tool for r in result.rejected] == ["ask_reviewer"]


def test_the_box_tool_opens_once() -> None:
    result = ea.propose(WINDOW, [open_box(20, "A"), open_box(21, "B")])
    assert len(result.proposals) == 1
    assert "already open" in result.rejected[0].reason


def test_the_box_tool_must_open_within_the_incident() -> None:
    result = ea.propose(WINDOW, [open_box(75)])
    assert result.proposals == []
    assert "within the incident" in result.rejected[0].reason


def test_no_window_means_no_bound() -> None:
    result = ea.propose(ea.IncidentWindow(), [open_box(500)])
    assert len(result.proposals) == 1


def test_the_name_is_stripped_and_must_have_words() -> None:
    result = ea.propose(WINDOW, [open_box(20, "  Bag  ")])
    assert result.proposals[0].args["name"] == "Bag"
    blank = ea.propose(WINDOW, [open_box(20, "   ")])
    assert blank.proposals == []
    assert "blank" in blank.rejected[0].reason


def test_an_unknown_tool_is_rejected() -> None:
    result = ea.propose(WINDOW, [ea.Call(tool="delete_item", args={})])
    assert result.rejected[0].reason == "There is no tool called 'delete_item'."


def test_extra_arguments_are_rejected() -> None:
    result = ea.propose(WINDOW, [ea.Call(tool="open_box_tool", args={"seconds": 20, "name": "Bag", "answer": "b"})])
    assert result.proposals == []
    assert result.rejected[0].tool == "open_box_tool"


# The draft's items: p1 is seen at 5 seconds, k1 has no second it is seen at.
ITEMS: dict[str, float | None] = {"p1": 5.0, "k1": None}


def open_item(key: str = "p1") -> ea.Call:
    return ea.Call(tool="open_box_tool", args={"item_key": key})


def test_the_box_tool_opens_on_an_existing_item_by_its_key() -> None:
    result = ea.propose(WINDOW, [open_item("p1")], ITEMS)
    assert [p.tool for p in result.proposals] == ["open_box_tool"]
    assert result.proposals[0].args == {"item_key": "p1"}
    assert "redraw its box" in result.proposals[0].summary
    assert result.rejected == []


def test_an_item_must_be_in_the_draft() -> None:
    result = ea.propose(WINDOW, [open_item("E1")], ITEMS)
    assert result.proposals == []
    assert result.rejected[0].reason == "No item with key 'E1' in the draft."


def test_no_draft_means_no_item_can_be_opened() -> None:
    result = ea.propose(WINDOW, [open_item("p1")])
    assert result.proposals == []
    assert "No item with key 'p1'" in result.rejected[0].reason


def test_an_item_with_no_second_it_is_seen_at_cannot_be_opened() -> None:
    result = ea.propose(WINDOW, [open_item("k1")], ITEMS)
    assert result.proposals == []
    assert "no second it is seen at" in result.rejected[0].reason


def test_an_item_opening_takes_no_seconds_or_name_from_the_model() -> None:
    result = ea.propose(WINDOW, [ea.Call(tool="open_box_tool", args={"item_key": "p1", "seconds": 6})], ITEMS)
    assert result.proposals == []
    assert "item_key alone" in result.rejected[0].reason


def test_new_evidence_needs_its_seconds_and_a_name() -> None:
    result = ea.propose(WINDOW, [ea.Call(tool="open_box_tool", args={"seconds": 12})], ITEMS)
    assert result.proposals == []
    assert "needs its seconds and a name" in result.rejected[0].reason


def test_an_item_opening_counts_as_the_box_tool_opening() -> None:
    result = ea.propose(WINDOW, [open_item("p1"), open_box(20, "Bag")], ITEMS)
    assert [p.tool for p in result.proposals] == ["open_box_tool"]
    assert [r.reason for r in result.rejected] == ["The box tool is already open for this evidence."]
