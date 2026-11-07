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

"""Follow-up questions read against the conversation, without a model: template mode, and when the chat model fails.

A question that leans on the turns before it ("what happened next?", "what happened to him?") is answered when the
conversation settles what it means, and otherwise gets a short question back. It is never guessed: two people who could
be "him" are named and the reviewer chooses.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Any

from vss_agents.utils import report_answers

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

_MASCULINE = re.compile(r"\b(?:he|him|his)\b")
_FEMININE = re.compile(r"\b(?:she|her|hers)\b")
_PLURAL = re.compile(r"\b(?:they|them|their)\b")
_POINTER = re.compile(r"\b(?:he|she|him|her|his|hers|they|them|their)\b")
_MEN = frozenset({"man", "men", "boy", "boys", "guy", "guys"})
_WOMEN = frozenset({"woman", "women", "girl", "girls"})
_NEXT = re.compile(
    r"^\s*(?:and\s+|so\s+|ok\s+)?(?:then\s+)?(?:what\s+)?(?:(?:happened|happens|happen|came|comes|occurred)\s+)?"
    r"(?:(?:did|do)\s+(?:he|she|they)\s+do\s+)?(?:next|then|after that|afterwards?|after)\s*[?.!]*\s*$"
)
_BEFORE_THAT = re.compile(r"^\s*(?:and\s+|so\s+)?(?:what\s+)?(?:(?:happened|came)\s+)?before that\s*[?.!]*\s*$")
# What a composed answer settles whoever "he" is: a statement about names or injuries is no guess about one person.
_ANY_SUBJECT = frozenset({"identity", "injury", "severity", "type", "location", "out_of_scope"})
LOOK_BACK = 4


def _turns(history: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The turns before the question, newest first."""
    return list(reversed(history[:-1]))[:LOOK_BACK]


def _last_answer(history: Sequence[Mapping[str, Any]]) -> str:
    return next((str(t.get("content") or "") for t in _turns(history) if t.get("role") == "assistant"), "")


def _anchor(answer: str, view: report_answers.ReportView, *, earliest: bool) -> float | None:
    """The second of the timeline event an earlier answer told last (or first), found by its time. Only event times
    count: an answer about people also says "seen from 0:05 to 1:00"."""
    told = []
    for event in view.timeline:
        start = report_answers.clock(event.get("start_seconds"))
        if start and re.search(rf"(?<![\d:\u2013-])(?<!to ){re.escape(start)}(?![\d:])", answer):
            told.append(float(event["start_seconds"]))
    if not told:
        return None
    return min(told) if earliest else max(told)


def _fits(pronoun_question: str, person: report_answers.Item) -> bool:
    """Whether a person's own label allows the pronoun. A label that does not say allows either."""
    head = report_answers.entity_head(person)
    if _MASCULINE.search(pronoun_question):
        return head not in _WOMEN
    if _FEMININE.search(pronoun_question):
        return head not in _MEN
    return True


def _recently_named(history: Sequence[Mapping[str, Any]], view: report_answers.ReportView) -> list[report_answers.Item]:
    """The people the newest earlier turn that names anyone names."""
    for turn in _turns(history):
        named = [view.item(i) for i in report_answers.named_items(str(turn.get("content") or ""), view)]
        people = [item for item in named if item is not None and item.is_person]
        if people:
            return people
    return []


def clarification(view: report_answers.ReportView, candidates: Sequence[report_answers.Item] = ()) -> str:
    """A short question back, naming the people it could mean."""
    people = list(candidates) or [item for item in view.items if item.is_person]
    if len(people) < 2:
        return 'Which person or object do you mean? Name them, for example "the man in the white shirt".'
    mentions = view.mentions()
    names = list(dict.fromkeys(mentions[p.item_id] for p in people))
    if len(names) < 2:  # two people the report labels alike: the names alone cannot tell them apart
        return "The report describes these people alike, so please say which one you mean, or when they appear."
    return f"Which person do you mean: {', '.join(names[:-1])} or {names[-1]}?"


def _clarify(
    view: report_answers.ReportView, candidates: Sequence[report_answers.Item] = ()
) -> report_answers.ComposedAnswer:
    return report_answers.ComposedAnswer(clarification(view, candidates), (), True, "clarify")


def resolve(
    question: str, history: Sequence[Mapping[str, Any]], view: report_answers.ReportView
) -> report_answers.ComposedAnswer | None:
    """The answer to a question that leans on the conversation, a question back, or ``None`` when it stands alone.

    ``history`` holds the conversation with this question as its last turn.
    """
    q = report_answers.read_question(question, view)
    earlier = _BEFORE_THAT.search(q) is not None
    if earlier or _NEXT.search(q):
        for text in (_last_answer(history), *(str(t.get("content") or "") for t in _turns(history))):
            anchor = _anchor(text, view, earliest=earlier)
            if anchor is not None:
                return report_answers.next_events(view, anchor, earlier=earlier)
        return report_answers.ComposedAnswer(
            f"{'Before' if earlier else 'After'} which moment? Ask about an event or a time, for example "
            '"what happened after 0:30?".',
            (),
            True,
            "clarify",
        )
    if not _POINTER.search(q) or report_answers.named_items(question, view):
        return None
    composed = report_answers.compose(question, view)
    if composed.kind in _ANY_SUBJECT or (composed.kind == "sequence" and not composed.insufficient_evidence):
        return None
    people = [item for item in view.items if item.is_person]
    if _PLURAL.search(q) and not _MASCULINE.search(q) and not _FEMININE.search(q) and len(people) != 1:
        return None  # "they" reads as everyone: nothing here needs one person picked
    fitting = [person for person in people if _fits(q, person)]
    if len(fitting) == 1:
        return report_answers.about_item(view, fitting[0])
    recent = [person for person in _recently_named(history, view) if _fits(q, person)]
    if len(recent) == 1:
        return report_answers.about_item(view, recent[0])
    return _clarify(view, recent or fitting)
