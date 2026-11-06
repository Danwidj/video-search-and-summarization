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
"""Which report event a time in a model's answer belongs to. Pure: code decides, from the report's timeline.

A model writes times as free text, so a time can exist in the report and still sit beside the wrong event: "exploding at
1:31" names the end of an event that starts at 1:12. So a written time counts only when the clause it stands in
describes a timeline event and the time fits that event:

- a single time must be the event's start, or its end after "by", "until" or the like;
- a range must run from an event's start to an event's end, both events described by the sentence;
- a time may also be an item's own stored second when the clause names that item, or the incident window's.

Anything else is left unattributed, and a client shows it as plain text: no jump is better than a wrong one. A clause
that describes one event clearly and gives no time gets that event's time from the report. Words that most events
share ("man", "shirt") do not tell events apart, so only the others count.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
import re
from typing import TYPE_CHECKING
from typing import Any

from vss_agents.utils import report_answers

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

_TIME = re.compile(r"(?<![\w:./])(?:(\d{1,2}):([0-5]\d):([0-5]\d)|(\d{1,3}):([0-5]\d))(?:\.\d+)?(?![\w:])")
_RANGE_JOIN = re.compile(r"^\s*(?:\u2013|\u2014|-|to|until|through)\s*$")
_CLAUSE_END = re.compile(r"(?<=[.!?])\s+|[;,]\s+|\n+")
_ENDS_THEN = re.compile(
    r"(?:\bby|\buntil|\btill|\bthrough|\bup to|\bend(?:s|ed|ing)? (?:at|by)|\bfinish\w* (?:at|by))\s*\(?$", re.I
)
_NEGATED = re.compile(
    r"\b(?:does not|doesn't|do not|don't|did not|didn't|cannot|can't|no record|nor|never|without|not (?:state|mention|"
    r"record|establish|identify|show|describe|confirm|say))\b",
    re.I,
)
_DESCRIBES = re.compile(r"\b(?:described|is called|is named|looks like|identified as|classified)\b", re.I)
_JOINS = re.compile(r"\s+(?:and|then)\s+", re.I)
_ABOUT_WINDOW = re.compile(r"\b(?:incident|window|video|clip|recording)\b", re.I)
_PEOPLE = frozenset({"man", "men", "woman", "women", "person", "people", "guy", "boy", "girl", "child"})
MIN_WORDS_TO_ATTACH = 2


@dataclass(frozen=True)
class Event:
    start: float | None
    end: float | None
    words: frozenset[str]  # the words that tell this event apart
    all_words: frozenset[str]


@dataclass(frozen=True)
class Attribution:
    content: str
    unattributed: tuple[str, ...]


def _stem(word: str) -> str:
    return re.sub(r"(?:ing|ed|es|s)$", "", word)[:5]


def _stems(text: str) -> set[str]:
    """A text's content words, with a short stem so "exploding" meets "explosion" and "pushing" meets "pushes"."""
    words = report_answers.action_words(text) - _PEOPLE
    return words | {_stem(word) for word in words if len(word) >= 4}


def _seconds(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def events(context: Mapping[str, Any], mentions: Mapping[str, str]) -> list[Event]:
    """The timeline's events, each with the words that set it apart from the others."""
    raw = [e for e in context.get("timeline") or [] if isinstance(e, dict)]
    stems = [_stems(report_answers.resolve_references(str(e.get("description") or ""), mentions)) for e in raw]
    limit = 1 if len(raw) <= 2 else max(1, len(raw) // 2)  # a word in more events than this tells none apart
    out = []
    for event, words in zip(raw, stems, strict=True):
        shared = {w for w in words if sum(w in other for other in stems) > limit}
        start, end = _seconds(event.get("start_seconds")), _seconds(event.get("end_seconds"))
        out.append(Event(start, end, frozenset(words - shared), frozenset(words)))
    return out


def _clauses(text: str) -> list[tuple[int, int]]:
    """The spans of ``text`` between clause marks. A decimal or a time's colon is no mark."""
    spans, start = [], 0
    for mark in _CLAUSE_END.finditer(text):
        spans.append((start, mark.start()))
        start = mark.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _sentence(text: str, position: int) -> str:
    starts = [0, *(m.end() for m in re.finditer(r"(?<=[.!?])\s+|\n+", text))]
    start = max(s for s in starts if s <= position)
    following = [s for s in starts if s > position]
    return text[start : following[0] if following else len(text)]


def _best(text: str, timeline: Sequence[Event]) -> tuple[int, list[Event]]:
    """The highest overlap of ``text`` with an event, and every event that reaches it."""
    words = _stems(text)
    scores = [len(words & event.words) for event in timeline]
    top = max(scores, default=0)
    return top, [event for event, score in zip(timeline, scores, strict=True) if score == top and top]


def _whole(match: re.Match[str]) -> int:
    hours, minutes, seconds, short_minutes, short_seconds = match.groups()
    if hours is not None:
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return int(short_minutes) * 60 + int(short_seconds)


def _item_seconds(clause: str, view: report_answers.ReportView, context: Mapping[str, Any]) -> set[int]:
    """The stored seconds of the items a clause names."""
    named = report_answers.text_items([clause], view)
    out: set[int] = set()
    for item in context.get("items") or []:
        if item.get("item_id") in named:
            for key in ("timestamp_seconds", "first_seen_seconds", "last_seen_seconds", "evidence_second"):
                value = _seconds(item.get(key))
                if value is not None:
                    out.add(int(value))
    return out


def _window_seconds(context: Mapping[str, Any]) -> set[int]:
    incident = context.get("incident") or {}
    values = (_seconds(incident.get("start_timestamp")), _seconds(incident.get("end_timestamp")))
    return {int(value) for value in values if value is not None}


def _described(text: str, timeline: Sequence[Event]) -> list[Event]:
    """The events a text describes: those it matches best on telling words, else on any word they hold."""
    top, best = _best(text, timeline)
    if top:
        return best
    words = _stems(text)
    return [event for event in timeline if words & event.all_words]


def _single_fits(
    match: re.Match[str],
    span: tuple[int, int],
    text: str,
    timeline: Sequence[Event],
    view: report_answers.ReportView,
    context: Mapping[str, Any],
) -> bool:
    """Whether a lone time fits what it stands beside. The nearest text that describes an event decides: the part of
    the clause it is in, then the clause, then the sentence. Only text that describes no event may fall to an item's
    own second or the incident window, so "exited at 0:46" cannot pass on a person's last-seen second."""
    second = _whole(match)
    ends_here = bool(_ENDS_THEN.search(text[max(0, match.start() - 14) : match.start()]))
    start, end = span
    before = [m.end() for m in _JOINS.finditer(text, start, match.start())]
    after = [m.start() for m in _JOINS.finditer(text, match.end(), end)]
    clause = text[start:end]
    nearest = text[before[-1] if before else start : after[0] if after else end]
    for part in (nearest, clause, _sentence(text, match.start())):
        described = _described(part, timeline)
        if described:
            return any(e.start == second or (ends_here and e.end == second) for e in described)
    if second in _item_seconds(clause, view, context):
        return True
    return second in _window_seconds(context) and bool(_ABOUT_WINDOW.search(clause))


def _range_fits(first: re.Match[str], last: re.Match[str], text: str, timeline: Sequence[Event]) -> bool:
    """A range runs from an event's start to an event's end, and the sentence describes both."""
    words = _stems(_sentence(text, first.start()))
    described = [event for event in timeline if words & event.all_words]
    return any(e.start == _whole(first) for e in described) and any(e.end == _whole(last) for e in described)


def unattributed_times(
    text: str, timeline: Sequence[Event], view: report_answers.ReportView, context: Mapping[str, Any]
) -> list[str]:
    """The times written in ``text`` that cannot be tied to the event, item or window they stand beside."""
    spans = _clauses(text)
    matches = list(_TIME.finditer(text))
    out: list[str] = []
    skip = -1
    for index, match in enumerate(matches):
        if index == skip:
            continue
        following = matches[index + 1] if index + 1 < len(matches) else None
        if following is not None and _RANGE_JOIN.match(text[match.end() : following.start()]):
            skip = index + 1
            if not _range_fits(match, following, text, timeline):
                out += [match.group(0), following.group(0)]
            continue
        span = next(((a, b) for a, b in spans if a <= match.start() < b), (0, len(text)))
        if not _single_fits(match, span, text, timeline, view, context):
            out.append(match.group(0))
    return list(dict.fromkeys(out))


def _span(event: Event) -> str | None:
    start, end = report_answers.clock(event.start), report_answers.clock(event.end)
    if not start:
        return None
    return f"{start}\u2013{end}" if end and end != start else start


def _parts(text: str, start: int, end: int, timeline: Sequence[Event]) -> list[tuple[int, int]]:
    """A clause, split at "and" or "then" when it describes more than one event, so each can have its own time."""
    words = _stems(text[start:end])
    if sum(len(words & event.words) >= MIN_WORDS_TO_ATTACH for event in timeline) < 2:
        return [(start, end)]
    cuts = [m.start() for m in _JOINS.finditer(text, start, end)]
    return list(pairwise([start, *cuts, end]))


def _clear_winner(text: str, timeline: Sequence[Event]) -> Event | None:
    """The one event a text plainly describes: enough telling words, and at least twice any other event's."""
    words = _stems(text)
    ranked = sorted(timeline, key=lambda event: len(words & event.words), reverse=True)
    if not ranked or len(words & ranked[0].words) < MIN_WORDS_TO_ATTACH:
        return None
    runner_up = len(words & ranked[1].words) if len(ranked) > 1 else 0
    return ranked[0] if len(words & ranked[0].words) >= 2 * runner_up else None


def attach_times(text: str, timeline: Sequence[Event]) -> str:
    """``text`` with an event's time after each clause that describes that one event clearly and gives no time.

    A clause must plainly describe one event (:func:`_clear_winner`), or nothing is added. Each event gets its time once in an answer, and not at all if the answer already times it. A clause that denies something, or
    only says what an object is, is left alone: a time there would seem to vouch for it.
    """
    timed = {
        id(e)
        for start, end in _clauses(text)
        if _TIME.search(text[start:end])
        for e in _best(text[start:end], timeline)[1][:1]
    }
    out, position = [], 0
    for clause_start, clause_end in _clauses(text):
        for start, end in _parts(text, clause_start, clause_end, timeline):
            clause = text[start:end]
            if _TIME.search(clause) or _NEGATED.search(clause) or _DESCRIBES.search(clause):
                continue
            event = _clear_winner(clause, timeline)
            if event is None or id(event) in timed:
                continue
            span = _span(event)
            if span:
                timed.add(id(event))
                stop = len(clause.rstrip().rstrip(".!?"))
                out += [text[position : start + stop], f" ({span})"]
                position = start + stop
    out.append(text[position:])
    return "".join(out)


def affirmed(text: str) -> str:
    """The clauses of ``text`` that state something, without those that deny it."""
    return " ".join(text[a:b] for a, b in _clauses(text) if not _NEGATED.search(text[a:b]))


def attribute(
    answer: str,
    rest: str,
    context: Mapping[str, Any],
    view: report_answers.ReportView,
    mentions: Mapping[str, str],
) -> Attribution:
    """The answer's written times checked, and the missing ones attached to ``answer`` from the timeline. ``rest`` is
    the labelled text after it: its times are checked, but nothing is added to it."""
    timeline = events(context, mentions)
    written = unattributed_times(f"{answer}\n\n{rest}" if rest else answer, timeline, view, context)
    return Attribution(content=attach_times(answer, timeline), unattributed=tuple(written))
