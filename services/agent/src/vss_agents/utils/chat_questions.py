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

"""Reading a question before it is answered. Pure text: no report, no model.

- :func:`normalise` lower-cases a question, rewrites "take place" so it cannot read as a taking, and corrects a typo in
  a word that says what kind of answer is wanted. Only those words are corrected: correcting towards everyday words
  turned "fight" into "light" and "battle" into "bottle", which changes what a question claims.
- :func:`question_moment` finds the moment a question points at ("at 0:30", "after 30 seconds", "between 0:10 and 0:20").
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from typing import TYPE_CHECKING
from typing import Literal

if TYPE_CHECKING:
    from collections.abc import Collection

# A video time as the console reads one: m:ss or h:mm:ss, not inside a longer token.
TIME = re.compile(r"(?<![\w:./])(?:(\d{1,2}):([0-5]\d):([0-5]\d)|(\d{1,3}):([0-5]\d))(?:\.\d+)?(?![\w:])")
SECONDS_IN_TEXT = re.compile(r"(?<![\w.:])(\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*(\d+(?:\.\d+)?))?\s*(?:s|secs?|seconds?)\b")

_TAKE_PLACE = re.compile(r"\b(?:take|takes|took|taken|taking)\s+place\b")
_WORD = re.compile(r"[a-z]+")
_VOCABULARY = (
    "where",
    "location",
    "located",
    "involved",
    "involve",
    "happened",
    "happen",
    "happens",
    "happening",
    "stolen",
    "stole",
    "steal",
    "theft",
    "weapon",
    "weapons",
    "injured",
    "injury",
    "injuries",
    "attacker",
    "attackers",
    "attacked",
    "attack",
    "attacks",
    "victim",
    "victims",
    "people",
    "person",
    "summary",
    "summarise",
    "summarize",
    "timeline",
    "incident",
    "severity",
    "suspect",
    "describe",
    "description",
)
_VOCABULARY_SET = frozenset(_VOCABULARY)
# Real words a typo check would otherwise pull towards the vocabulary. Common short words are in ``protected``.
_REAL_WORDS = frozenset({"insured", "vocation", "allocation", "resolved", "evolved", "here", "there", "were", "wear"})
_MIN_TYPO_LENGTH = 4
_TYPO_CUTOFF = 0.8

# "at 30 seconds", "around the 30 second mark", "second 30": a bare number of seconds points at a moment only with such
# a word beside it, because "longer than 30 seconds" does not.
_NEAR = r"(?:at|around|about|near|after|before|by|from|to|until|and|since)\s+(?:the\s+)?"
_POINTED_SECONDS = re.compile(
    rf"\b{_NEAR}(\d+(?:\.\d+)?)\s*(?:s|secs?|seconds?)\b(?:\s+mark)?|\bsecond\s+(\d+(?:\.\d+)?)\b"
    r"|\b(\d+(?:\.\d+)?)\s*(?:s|secs?|seconds?)\s+mark\b"
)
_POINTED_MINUTES = re.compile(
    rf"\b{_NEAR}(\d+)\s*(?:m|mins?|minutes?)(?:\s*(?:and\s*)?(\d+)\s*(?:s|secs?|seconds?))?\b"
)
_AFTER = re.compile(r"\b(?:after|since|following|later than|from)\b")
_BEFORE = re.compile(r"\b(?:before|prior to|earlier than|until|up to|leading up to)\b")
_RANGE = re.compile(r"\b(?:between|from)\b|[-\u2013]")

Side = Literal["at", "after", "before"]


@dataclass(frozen=True)
class Moment:
    """Where a question points in the video: one second, a span, or everything after or before a second."""

    start: float
    end: float
    side: Side
    spans: tuple[tuple[int, int], ...]  # where the question writes the time(s)


def normalise(question: str, protected: Collection[str] = ()) -> str:
    """The question in lower case, with "take place" as "happen" and typos in intent words corrected.

    ``protected`` are words that are right as written (the report's own and common words): they are never corrected.
    """
    text = _TAKE_PLACE.sub("happen", question.lower())

    def correct(match: re.Match[str]) -> str:
        word = match.group(0)
        if len(word) < _MIN_TYPO_LENGTH or word in _VOCABULARY_SET or word in _REAL_WORDS or word in protected:
            return word
        close = difflib.get_close_matches(word, _VOCABULARY, n=1, cutoff=_TYPO_CUTOFF)
        return close[0] if close and close[0][0] == word[0] else word

    return _WORD.sub(correct, text)


def _whole_seconds(match: re.Match[str]) -> float:
    hours, minutes, seconds, short_minutes, short_seconds = match.groups()
    if hours is not None:
        return float(int(hours) * 3600 + int(minutes) * 60 + int(seconds))
    return float(int(short_minutes) * 60 + int(short_seconds))


def _found_times(text: str) -> list[tuple[float, tuple[int, int]]]:
    found = [(_whole_seconds(m), m.span()) for m in TIME.finditer(text)]
    for match in _POINTED_MINUTES.finditer(text):
        found.append((int(match.group(1)) * 60 + float(match.group(2) or 0), match.span()))
    for match in _POINTED_SECONDS.finditer(text):
        value = next(group for group in match.groups() if group is not None)
        span = match.span()
        if not any(span[0] < other[1] and other[0] < span[1] for _, other in found):
            found.append((float(value), span))
    return sorted(found, key=lambda entry: entry[1])


def question_moment(question: str) -> Moment | None:
    """The moment a lower-case question points at, or ``None`` when it points at none."""
    found = _found_times(question)
    if not found:
        return None
    spans = tuple(span for _, span in found)
    first = found[0][0]
    if len(found) >= 2 and _RANGE.search(question[: found[1][1][0]]):
        return Moment(min(first, found[1][0]), max(first, found[1][0]), "at", spans)
    before_time = question[: found[0][1][1]]
    side: Side = "after" if _AFTER.search(before_time) else "before" if _BEFORE.search(before_time) else "at"
    return Moment(first, first, side, spans)


def without_moment(question: str, moment: Moment) -> str:
    """The question with the times it writes taken out, for checking what else it asks."""
    out = question
    for start, end in sorted(moment.spans, reverse=True):
        out = f"{out[:start]} {out[end:]}"
    return out
