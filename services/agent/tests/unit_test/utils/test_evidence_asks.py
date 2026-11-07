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

"""Unit tests for the new-evidence rules: at most two questions, then one box tool opening."""

from vss_agents.utils import evidence_asks as ea

WINDOW = ea.IncidentWindow(start_timestamp=10, end_timestamp=60)


def ask(question: str = "Who is the man in the red hood?") -> ea.Call:
    return ea.Call(tool="ask_reviewer", args={"question": question})


def open_box(seconds: float = 24, name: str = "Red hood") -> ea.Call:
    return ea.Call(tool="open_box_tool", args={"seconds": seconds, "name": name})


def test_two_questions_then_the_box_tool_opens() -> None:
    result = ea.propose(WINDOW, 0, [ask("a"), ask("b"), open_box(30, "Red hood")])
    assert [p.tool for p in result.proposals] == ["ask_reviewer", "ask_reviewer", "open_box_tool"]
    assert result.proposals[2].args == {"seconds": 30, "name": "Red hood"}
    assert result.rejected == []


def test_a_third_question_is_rejected() -> None:
    result = ea.propose(WINDOW, 0, [ask("a"), ask("b"), ask("c")])
    assert len(result.proposals) == 2
    assert [r.tool for r in result.rejected] == ["ask_reviewer"]
    assert "2 questions" in result.rejected[0].reason


def test_questions_already_asked_count_against_the_cap() -> None:
    result = ea.propose(WINDOW, 1, [ask("a"), ask("b")])
    assert len(result.proposals) == 1
    assert len(result.rejected) == 1


def test_the_box_tool_can_open_with_no_question_asked() -> None:
    result = ea.propose(WINDOW, 0, [open_box(12, "Bag")])
    assert [p.tool for p in result.proposals] == ["open_box_tool"]


def test_no_question_may_follow_the_box_tool() -> None:
    result = ea.propose(WINDOW, 0, [open_box(), ask()])
    assert [p.tool for p in result.proposals] == ["open_box_tool"]
    assert "already open" in result.rejected[0].reason


def test_the_box_tool_opens_once() -> None:
    result = ea.propose(WINDOW, 0, [open_box(20, "A"), open_box(21, "B")])
    assert len(result.proposals) == 1
    assert "already open" in result.rejected[0].reason


def test_the_box_tool_must_open_within_the_incident() -> None:
    result = ea.propose(WINDOW, 0, [open_box(75)])
    assert result.proposals == []
    assert "within the incident" in result.rejected[0].reason


def test_no_window_means_no_bound() -> None:
    result = ea.propose(ea.IncidentWindow(), 0, [open_box(500)])
    assert len(result.proposals) == 1


def test_the_name_is_stripped_and_must_have_words() -> None:
    result = ea.propose(WINDOW, 0, [open_box(20, "  Bag  ")])
    assert result.proposals[0].args["name"] == "Bag"
    blank = ea.propose(WINDOW, 0, [open_box(20, "   ")])
    assert blank.proposals == []
    assert "blank" in blank.rejected[0].reason


def test_an_unknown_tool_is_rejected() -> None:
    result = ea.propose(WINDOW, 0, [ea.Call(tool="delete_item", args={})])
    assert result.rejected[0].reason == "There is no tool called 'delete_item'."


def test_extra_arguments_are_rejected() -> None:
    result = ea.propose(WINDOW, 0, [ea.Call(tool="ask_reviewer", args={"question": "a", "answer": "b"})])
    assert result.proposals == []
    assert result.rejected[0].tool == "ask_reviewer"


def test_a_rejected_question_does_not_use_up_the_cap() -> None:
    result = ea.propose(WINDOW, 0, [ea.Call(tool="ask_reviewer", args={"question": ""}), ask("a"), ask("b")])
    assert len(result.proposals) == 2
    assert len(result.rejected) == 1
