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
"""Reading a question: typos, "take place" and the moment a question points at. Pure text."""

import pytest

from vss_agents.utils import chat_questions


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("where the incident take place", "where the incident happen"),
        ("Where did it take place?", "where did it happen?"),
        ("when did this took place", "when did this happen"),
        ("wher did it hapen", "where did it happen"),
        ("who was involed", "who was involved"),
        ("was anything stollen", "was anything stolen"),
        ("any wepons?", "any weapons?"),
        ("who is the atacker", "who is the attacker"),
    ],
)
def test_a_question_is_read_past_its_typos_and_take_place(question: str, expected: str) -> None:
    assert chat_questions.normalise(question) == expected


@pytest.mark.parametrize(
    "question",
    ["was there a fight", "was it a battle", "what was on the plate", "was the car insured", "where were they"],
)
def test_everyday_words_are_left_as_written(question: str) -> None:
    assert chat_questions.normalise(question, {"were", "there", "was"}) == question


def test_a_word_the_report_uses_is_never_corrected() -> None:
    assert chat_questions.normalise("what about the wepon", {"wepon"}) == "what about the wepon"


@pytest.mark.parametrize(
    ("question", "start", "end", "side"),
    [
        ("what happened at 0:30?", 30, 30, "at"),
        ("what is going on at 1:05", 65, 65, "at"),
        ("what happened around 30 seconds?", 30, 30, "at"),
        ("what was happening at the 45 second mark", 45, 45, "at"),
        ("what happens at second 12", 12, 12, "at"),
        ("what happened after 0:30", 30, 30, "after"),
        ("what happened before 1:00?", 60, 60, "before"),
        ("what happened between 0:10 and 0:20?", 10, 20, "at"),
        ("what happened from 0:10 to 0:20", 10, 20, "at"),
        ("what happens at 1 minute 5 seconds", 65, 65, "at"),
    ],
)
def test_a_moment_is_found(question: str, start: float, end: float, side: str) -> None:
    moment = chat_questions.question_moment(question)
    assert moment is not None and (moment.start, moment.end, moment.side) == (start, end, side)


@pytest.mark.parametrize("question", ["was it longer than 30 seconds?", "what happened?", "who are the two men?"])
def test_a_number_that_points_at_no_moment_is_none(question: str) -> None:
    assert chat_questions.question_moment(question) is None


def test_the_written_time_can_be_taken_out_of_the_question() -> None:
    moment = chat_questions.question_moment("what happened at 0:30?")
    assert moment is not None
    assert "0:30" not in chat_questions.without_moment("what happened at 0:30?", moment)
