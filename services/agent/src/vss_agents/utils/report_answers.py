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

"""Answers composed from one incident report, without a model: the chat route's template mode.

The template mode used to answer every question with the evidence items whose words matched it, ids in the prose
("5 relevant item(s) were identified: human (E1) in vc83... (incident at 134s); ..."). A question about what happened
shares no words with any item, so it got the report's first five items. This module answers from the report itself
(its incident fields, items and timeline), by the kind of question:

- **what happened, or the order of events:** the timeline in time order, one line per event with its time, then what
  the report could not establish about those events; the incident description when there is no timeline. An event
  wholly outside the incident window is shown as context before or after the incident, not dropped: it may be real
  lead-up or aftermath;
- **who:** the people, with how they look and when they are seen;
- **objects** (weapons, tools, what was used or taken, or a named object): the instruments, with who held them, and
  the assets. A named object the report does not record is said to be absent;
- **when, or how long:** the incident window, or when a named item is seen;
- **severity** and **type**;
- **what came after or before a moment:** the events on that side of the event the question points at, never the whole
  timeline; a moment the report does not record is said to be missing. What followed the incident is the timeline's
  events after its window;
- **anything else:** the timeline events that share the question's words; otherwise a plain statement that the report
  does not say, with no citations.

Item ids are references inside the report: the P1 prompt has timeline sentences say "E1 strikes E2 with I1". Before
any report text reaches an answer, each id is resolved to its item's own short description
(:func:`resolve_references`). The ids an answer relies on are returned separately, for the structured citations. An id
is written in the prose only when the question asks for ids. Every sentence comes from a report field; nothing is
inferred beyond it.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping
    from collections.abc import Sequence

ITEM_KINDS = (
    ("entities", "entity_id", "entity"),
    ("instruments", "instrument_id", "instrument"),
    ("assets", "asset_id", "asset"),
)
MAX_EVENTS = 8
MAX_TIMELINE_EVENTS = 12
MAX_UNCERTAINTIES = 3
HUMAN_TYPES = frozenset({"human", "person", "people", "man", "woman", "child", "pedestrian"})
NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")

_ID_TOKEN = r"(?:new-)?[EIA][0-9]{1,3}"  # the contract's ids, and the console's ids for items added in a draft
_ID = re.compile(rf"(?<![\w-])({_ID_TOKEN})(?![\w-])")
NEUTRAL = {"E": "a person", "I": "an object", "A": "an item"}
_ASKS_IDS = re.compile(r"\b(?:ids?|identifiers?|item[_ ]ids?)\b")
_CHRONOLOGY = re.compile(
    r"\b(?:what (?:happen\w*|went on|occurred)|happen(?:ed|s|ing)?|in order|order of|sequence|timeline|"
    r"chronolog\w*|step by step|walk me through|events?|describe|summar\w*|recap|overview|tell me about)\b"
)
_PEOPLE = re.compile(
    r"\b(?:who|whom|people|persons?|men|women|suspects?|victims?|attackers?|assailants?|offenders?|individuals?|"
    r"humans?|anyone|someone|involved)\b"
)
_OBJECTS = re.compile(
    r"\b(?:objects?|items?|weapons?|tools?|instruments?|assets?|property|taken|stolen|steal\w*|damaged?|"
    r"carr(?:y|ied|ying)|hold(?:ing)?|held|used|using|harm\w*|things?)\b"
)
# A question that names a kind of object ("which objects were involved?") asks about objects even when it also uses
# a word that can mean people ("involved", "anyone"); only a word that names people makes it a people question.
_OBJECT_KINDS = re.compile(r"\b(?:objects?|items?|things?|tools?|instruments?|assets?|property|weapons?)\b")
_PEOPLE_NAMED = re.compile(
    r"\b(?:who|whom|people|persons?|men|women|suspects?|victims?|attackers?|assailants?|offenders?|humans?)\b"
)
_WHEN = re.compile(
    r"\b(?:when|what time|how long|duration|start(?:ed|s)?|end(?:ed|s)?|begin\w*|at what (?:second|point|time|moment))\b"
)
_SEVERITY = re.compile(r"\b(?:severity|severe|serious\w*|danger\w*|risk\w*)\b")
# "What was taken?": a question about a taking, and the event wording that records one.
_TAKEN = re.compile(
    r"\b(?:taken|take|took|stole|stolen|steal\w*|theft|thie(?:f|ves|ving)|missing|robb\w*|rob|loot\w*|grab\w*|"
    r"snatch\w*|removed?|made off|carried (?:off|away))\b"
)
_TAKING = re.compile(
    r"\b(?:takes?|took|taken|taking|steal\w*|stole|stolen|grab\w*|snatch\w*|remov\w*|pick(?:s|ed|ing)? up|"
    r"carr(?:y|ies|ied|ying) (?:\w+ )?(?:away|off|out)|(?:walks?|walked|runs?|ran|leaves?|left|flees?|fled) "
    r"(?:off |away )?with|made off|pocket\w*|loot\w*|empt(?:y|ies|ied|ying))\b"
)
# "What could cause harm?": the report's instruments, each with its threat level.
_HARM = re.compile(r"\b(?:harm\w*|hurt\w*|injur\w*|threat\w*|weapons?|hazard\w*|unsafe|lethal|deadly|armed)\b")
_TYPE = re.compile(
    r"\b(?:(?:what|which) (?:kind|type|sort|category) of|type of incident|kind of incident|classif\w*|category)\b"
)
_HOW_MANY = re.compile(r"\bhow many\b")
_PRESENCE = re.compile(r"^\s*(?:is|are|was|were|did|does|do|has|have|had)\b|\bany\b")
# A bare existence question ("is there a crowbar?", "any knives?"): the only yes/no question a list of items can answer.
_EXISTENCE = re.compile(r"^\s*(?:(?:is|are|was|were)\s+there\b|any\b)")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "done",
        "has",
        "have",
        "had",
        "there",
        "here",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "he",
        "him",
        "his",
        "she",
        "her",
        "we",
        "you",
        "your",
        "i",
        "me",
        "my",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "any",
        "some",
        "all",
        "each",
        "every",
        "no",
        "not",
        "yes",
        "can",
        "could",
        "would",
        "should",
        "will",
        "may",
        "might",
        "must",
        "see",
        "seen",
        "seem",
        "show",
        "shows",
        "shown",
        "tell",
        "told",
        "say",
        "says",
        "said",
        "report",
        "video",
        "clip",
        "incident",
        "incidents",
        "happen",
        "happened",
        "happens",
        "happening",
        "order",
        "please",
        "also",
        "just",
        "only",
        "very",
        "much",
        "many",
        "more",
        "most",
        "other",
        "another",
        "one",
        "two",
        "three",
        "first",
        "then",
        "next",
        "last",
        "before",
        "after",
        "time",
        "times",
        "involved",
        "kind",
        "type",
        "sort",
        "category",
        "describe",
        "description",
        "summary",
        "summarise",
        "summarize",
        "events",
        "event",
        "timeline",
        "sequence",
        "people",
        "person",
        "persons",
        "who",
        "objects",
        "object",
        "items",
        "item",
        "things",
        "thing",
        "like",
        "look",
        "looks",
        "looking",
        "wear",
        "wears",
        "wearing",
        "cause",
        "caused",
        "causes",
        "causing",
        "could",
        "doing",
        "going",
        "get",
        "got",
        "make",
        "made",
        "take",
        "took",
        "give",
        "gave",
        "know",
        "think",
        "need",
        "want",
        "way",
        "ever",
        "still",
        "really",
    ]
)
# Words every uncertainty uses whatever it is about: sharing one does not relate it to an event.
_UNCERTAINTY_FILLER_TEXT = (
    "unclear clear clearly exact exactly visible identifiable identified identify identity identities unknown certain "
    "cannot determine determined whether nature reason established confirm confirmed individual individuals"
)
_UNCERTAINTY_FILLER = frozenset(_UNCERTAINTY_FILLER_TEXT.split())
# Where a person's or animal's label stops naming what it is ("man in blue shirt", "dog with a collar").
_LABEL_HEAD_END = re.compile(r"\s(?:in|with|wearing|near|on|at|inside|lying|walking|standing|carrying|holding)\s")
# An outfit in a label ("man in white shirt and dark pants"): an event may name either part of it.
_LABEL_OUTFIT = re.compile(r"^(.+?\s(?:in|wearing)\s)(.+\sand\s.+)$")
# Words too general to identify one object on their own.
_VAGUE_NAMES = frozenset({"object", "objects", "item", "items", "thing", "things"})
# A question about one moment in the order of events, not about the whole of it.
_SEQUENCE = re.compile(r"\b(?:after|afterwards?|before|next|then|following|prior to|until|later|earlier|leading up)\b")
_EARLIER = re.compile(r"\b(?:before|prior to|earlier|leading up)\b")
_IMMEDIATE = re.compile(r"\b(?:immediately|right after|straight after|just after|directly after)\b")
_AFTER_INCIDENT = re.compile(
    r"\bafter (?:the |this )?(?:incident|attack|assault|altercation|fight|event)\b(?: (?:ended|was over|finished|stopped))?"
    r"|\bafter (?:it|that) (?:ended|was over|finished|stopped)\b"
)
# Past forms the plural rules cannot reach, so "fell" meets an event that says "falls".
_PAST_FORMS = {
    "fell": "fall",
    "fallen": "fall",
    "ran": "run",
    "struck": "strike",
    "threw": "throw",
    "thrown": "throw",
    "stole": "steal",
    "stolen": "steal",
    "left": "leave",
    "went": "go",
    "came": "come",
    "broke": "break",
    "broken": "break",
    "shot": "shoot",
    "held": "hold",
}
_PEOPLE_NOUNS = frozenset(
    {"man", "men", "woman", "women", "guy", "boy", "girl", "child", "attacker", "victim", "suspect"}
)
# Words that ask nothing beyond the kind of answer: "who appears", "what was identified".
_PLAIN_TEXT = (
    "appear appears anything anyone identified identify recorded record listed list mentioned present there affected "
    "rated rating level given part during between finish finishes timestamp timestamps point place individual individuals"
)
_PLAIN_WORDS = frozenset(_PLAIN_TEXT.split())
# A question that leans on the conversation, or that asks for reasoning a template cannot give.
_CONTEXT = re.compile(
    r"\b(?:he|she|they|him|her|them|his|hers|their|next|else|afterwards?|that one|this one|the other|"
    r"did that|was that|that happen\w*)\b"
)
# A judgement about one thing ("was the object a weapon?"), which a list of items cannot settle.
_JUDGEMENT = re.compile(r"^\s*(?:was|is|were|are)\s+(?:the|that|this|those|these)\b")
_REASONING = re.compile(r"^\s*(?:why|how come)\b|\bhow did\b|\bexplain\b|\bbecause\b|\breason\b")
_THIS_INCIDENT = re.compile(r"\b(?:in|of|for|during) (?:this|the) (?:event|incident)\b")
_TIME_FIRST = re.compile(r"^\s*(?:when|what time|how long|at what (?:second|point|time|moment))\b")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def clock(seconds: Any) -> str | None:
    """A video time as the console shows it: ``m:ss``, or ``h:mm:ss`` from an hour."""
    value = _num(seconds)
    if value is None:
        return None
    whole = max(0, math.floor(value))
    hours, minutes, rest = whole // 3600, whole % 3600 // 60, whole % 60
    return f"{hours}:{minutes:02d}:{rest:02d}" if hours else f"{minutes}:{rest:02d}"


def _tokens(text: str) -> list[str]:
    """The content words of a text, in order, as written (lower case)."""
    return [w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP]


def _variants(word: str) -> set[str]:
    """A word and its likely singulars, for matching only ("knives" meets "knife", "witnesses" meets "witness")."""
    out = {word}
    if len(word) > 4 and word.endswith("ies"):
        out.add(word[:-3] + "y")
    elif len(word) > 4 and word.endswith("ves"):
        out |= {word[:-3] + "f", word[:-3] + "fe"}
    elif len(word) > 3 and word.endswith("es"):
        out |= {word[:-2], word[:-1]}
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        out.add(word[:-1])
    return out


def _words(text: str) -> set[str]:
    return {variant for word in _tokens(text) for variant in _variants(word)}


_ARTICLES = frozenset({"a", "an", "the", "some", "any"})


def term_sets(text: Any) -> list[frozenset[str]]:
    """Each word of ``text`` but its articles, with its likely singulars, for whole-word matching: ``"glass bottles"``
    gives ``[{"glass"}, {"bottles", "bottle", "bottl"}]``. Unlike the composer's own word sets it keeps short and
    common words, since a filter or search phrase may hinge on one ("TV", "two")."""
    return [frozenset(_variants(word)) for word in _WORD.findall(str(text or "").lower()) if word not in _ARTICLES]


def _lower_first(text: str) -> str:
    first = text.split(" ", 1)[0]
    return text if len(first) > 1 and first.isupper() else text[:1].lower() + text[1:]


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentence_case(text: str) -> str:
    text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text.strip())
    return text


def _first_clause(text: str) -> str:
    return re.split(r"[,;.]", text.strip(), maxsplit=1)[0].strip()


def _article(text: str, *, definite: bool) -> str:
    text = text.strip().rstrip(".")
    if re.match(r"(?i)^(?:the|a|an|this|that|his|her|their|its)\b", text):
        return _lower_first(text)
    if definite:
        return f"the {_lower_first(text)}"
    return f"{'an' if text[:1].lower() in 'aeiou' else 'a'} {_lower_first(text)}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else n} {singular if n == 1 else plural}"


def _join(parts: Sequence[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


@dataclass(frozen=True)
class Item:
    """One entity, instrument or asset of the report, as the answers need it."""

    kind: str
    item_id: str
    name: str = ""
    description: str = ""
    label: str = ""
    entity_type: str = ""
    seconds: float | None = None
    first_seen: float | None = None
    last_seen: float | None = None
    holder: str | None = None
    threat_level: int | None = None

    @property
    def is_person(self) -> bool:
        return self.kind == "entity" and self.entity_type in HUMAN_TYPES

    @property
    def words(self) -> set[str]:
        return _words(" ".join((self.name, self.description, self.label, self.entity_type)))

    @property
    def name_words(self) -> set[str]:
        """The words that name the item (its name or label, or a person's type): what an event about it would say."""
        return _words(" ".join((self.name, self.label, self.entity_type if self.kind == "entity" else "")))

    def mention(self) -> str:
        """How an answer names the item: its short visual label or name, else its description's first clause."""
        if self.kind == "entity":
            text = self.label or _first_clause(self.description) or self.entity_type or "person"
        else:
            text = self.name or self.label or _first_clause(self.description) or self.kind
        return _article(text, definite=True)

    def introduce(self, mentions: Mapping[str, str]) -> str:
        """The item named for the first time: how it looks (an entity) or what it is (an object)."""
        if self.kind == "entity":
            text = self.description or self.label or self.entity_type or "person"
            return _article(_resolve_plain(text, mentions), definite=False)
        text = _article(
            _resolve_plain(self.name or self.label or self.description or self.kind, mentions), definite=False
        )
        detail = _first_clause(self.description)
        if detail and self.name and _words(detail) - _words(self.name):
            text += f" ({_lower_first(_resolve_plain(detail, mentions))})"
        return text

    def seen(self) -> str:
        first, last = clock(self.first_seen), clock(self.last_seen)
        if first and last and first != last:
            return f"seen from {first} to {last}"
        moment = first or clock(self.seconds)
        return f"seen at {moment}" if moment else ""


class Mentions(dict[str, str]):
    """Item id to how the answer names it; ``retired`` holds the ids of the base version that a draft removed."""

    retired: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ReportView:
    """One report version (or an unsaved draft): incident fields, items and the timeline in time order.

    ``retired`` are the ids of base-version items the draft removed: report text written before the edit may still
    refer to them, and they read as a neutral "a person" or "an object".
    """

    incident: Mapping[str, Any]
    items: tuple[Item, ...]
    timeline: tuple[Mapping[str, Any], ...]
    retired: frozenset[str] = frozenset()
    uncertainties: tuple[str, ...] = ()

    def item(self, item_id: str | None) -> Item | None:
        return next((i for i in self.items if i.item_id == item_id), None) if item_id else None

    def mentions(self) -> Mentions:
        """Each item's mention, any id inside one (a label quoting another item) resolved in a single pass."""
        base = Mentions({i.item_id: i.mention() for i in self.items})
        base.retired = self.retired
        resolved = {item_id: _resolve_plain(text, base) for item_id, text in base.items()}
        # Labels that name each other ("man beside E2", "man beside E1") still hold an id after one pass: it reads
        # neutrally rather than recursing.
        neutral = Mentions()
        neutral.retired = frozenset(base) | self.retired
        final = Mentions({item_id: _resolve_plain(text, neutral) for item_id, text in resolved.items()})
        final.retired = self.retired
        return final


def item_ids(report: Mapping[str, Any] | None) -> set[str]:
    """Every entity, instrument and asset id a report holds."""
    report = report if isinstance(report, dict) else {}
    return {
        str(raw[id_field]).strip()
        for key, id_field, _ in ITEM_KINDS
        for raw in report.get(key) or []
        if isinstance(raw, dict) and str(raw.get(id_field) or "").strip()
    }


def overlay_draft(base: Mapping[str, Any] | None, draft: Mapping[str, Any]) -> dict[str, Any]:
    """The report an unsaved draft stands for: the base version with the reviewer's incident fields and items.

    The console sends a draft with only the fields a reviewer edits (incident type, times, description, severity and the
    items). As a human save does (the console's ``humanRevisionContent``), the model-only fields (title, severity reason,
    confidence, location, timeline) come from the base version.
    """
    out: dict[str, Any] = dict(base or {})
    raw_base, raw_draft = out.get("incident"), draft.get("incident")
    base_incident: dict[str, Any] = raw_base if isinstance(raw_base, dict) else {}
    draft_incident: dict[str, Any] = raw_draft if isinstance(raw_draft, dict) else {}
    out["incident"] = {**base_incident, **draft_incident}
    for key, _, _ in ITEM_KINDS:
        if key in draft:
            out[key] = draft[key]
    return out


def report_view(
    report: Mapping[str, Any] | None, evidence: Sequence[Mapping[str, Any]] = (), *, retired: Iterable[str] = ()
) -> ReportView:
    """The answerable view of a report; a revision saved without its report falls back to its evidence entries."""
    report = report if isinstance(report, dict) else {}
    seen = {
        (str(e.get("item_type")), str(e.get("item_id"))): _num(e.get("box_seconds", e.get("timestamp_seconds")))
        for e in evidence
        if isinstance(e, dict)
    }
    items: list[Item] = []
    for key, id_field, kind in ITEM_KINDS:
        for raw in report.get(key) or []:
            if not isinstance(raw, dict) or not str(raw.get(id_field) or "").strip():
                continue
            item_id = str(raw[id_field]).strip()
            threat = _num(raw.get("threat_level"))
            items.append(
                Item(
                    kind=kind,
                    item_id=item_id,
                    name=str(raw.get("name") or "").strip(),
                    description=str(raw.get("description") or "").strip(),
                    label=str(raw.get("label") or "").strip(),
                    entity_type=str(raw.get("type") or "").strip().lower(),
                    seconds=_num(raw.get("timestamp_seconds"))
                    if _num(raw.get("timestamp_seconds")) is not None
                    else seen.get((kind, item_id)),
                    first_seen=_num(raw.get("first_seen_seconds")),
                    last_seen=_num(raw.get("last_seen_seconds")),
                    holder=str(raw.get("entity_id") or "").strip() or None if kind == "instrument" else None,
                    threat_level=round(threat) if threat is not None else None,
                )
            )
    if not items:
        for entry in evidence:
            if not isinstance(entry, dict) or entry.get("item_type") not in ("entity", "instrument", "asset"):
                continue
            if not str(entry.get("item_id") or "").strip():
                continue
            kind = str(entry["item_type"])
            name = str(entry.get("item_name") or "").strip()
            items.append(
                Item(
                    kind=kind,
                    item_id=str(entry["item_id"]).strip(),
                    name="" if kind == "entity" else name,
                    description=str(entry.get("description") or "").strip(),
                    label=str(entry.get("label") or "").strip(),
                    entity_type=(name or "person").lower() if kind == "entity" else "",
                    seconds=_num(entry.get("box_seconds", entry.get("timestamp_seconds"))),
                )
            )
    events = [
        e for e in report.get("timeline") or [] if isinstance(e, dict) and str(e.get("description") or "").strip()
    ]
    events.sort(key=lambda e: (_num(e.get("start_seconds")) is None, _num(e.get("start_seconds")) or 0.0))
    raw_incident = report.get("incident")
    incident: dict[str, Any] = raw_incident if isinstance(raw_incident, dict) else {}
    held = {i.item_id for i in items}
    return ReportView(
        incident=incident,
        items=tuple(items),
        timeline=tuple(events),
        retired=frozenset(str(i) for i in retired if str(i) not in held),
        uncertainties=tuple(u.strip() for u in report.get("uncertainties") or [] if isinstance(u, str) and u.strip()),
    )


def _id_pattern(known: Iterable[str]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Each known id (longest first) and any other id-like token, as a whole token (never inside ``new-E2`` or
    ``E12``), and a parenthesised list of them."""
    alternatives = sorted({re.escape(i) for i in known if i}, key=len, reverse=True)
    core = "|".join([*alternatives, _ID_TOKEN])
    token = re.compile(rf"(?<![\w-])({core})(?![\w-])")
    group = re.compile(rf"\s*\(\s*((?:{core})(?:\s*(?:,|and|&)\s*(?:{core}))*)\s*\)")
    return token, group


def _replacement(token: str, mentions: Mapping[str, str], retired: frozenset[str]) -> str:
    """What an id-like token reads as: its item's mention; a neutral phrase for an id the report no longer holds
    (a draft's own ``new-`` id, an ``E``/``I`` id, or a removed item); an ``A``-number the report never used
    ("A4 paper", "the A1") is not a reference and stays as written."""
    if token in mentions:
        return mentions[token]
    bare = token.removeprefix("new-")
    if token.startswith("new-") or bare[:1] in "EI" or token in retired:
        return NEUTRAL.get(bare[:1], "an item")
    return token


def _resolve_plain(text: str, mentions: Mapping[str, str]) -> str:
    retired: frozenset[str] = getattr(mentions, "retired", frozenset())
    token, group = _id_pattern([*mentions, *retired])

    def drop(match: re.Match[str]) -> str:
        ids = token.findall(match.group(1))
        return "" if ids and all(i in mentions for i in ids) else match.group(0)

    return token.sub(lambda m: _replacement(m.group(1), mentions, retired), group.sub(drop, text))


def resolve_references(text: str, mentions: Mapping[str, str]) -> str:
    """Report text with each item-id reference resolved to that item's mention.

    ``"E1 strikes E2 with I1."`` becomes ``"The man in black strikes the cashier with the crowbar."``; a parenthesised id
    after a description (``"a man (E1)"``) is dropped, since the description already names it. An id the report no
    longer holds reads as a neutral "a person", "an object" or "an item" (:func:`_replacement`).
    """

    return _sentence_case(_resolve_plain(text, mentions))


def asks_for_ids(question: str) -> bool:
    """Whether a question asks for item ids ("what are the item ids of ..."): only then may ids appear in the prose."""
    return bool(_ASKS_IDS.search(question.lower()))


def names_an_id(question: str) -> bool:
    """Whether a question itself writes an item id ("who is holding stick I2?")."""
    return bool(_ID.search(question))


def referenced_ids(text: str, known: Iterable[str]) -> list[str]:
    """The known item ids a piece of report text refers to, in order of first reference."""
    known = set(known)
    token, _ = _id_pattern(known)
    out: list[str] = []
    for item_id in token.findall(text):
        if item_id in known and item_id not in out:
            out.append(item_id)
    return out


def replaced_ids(text: str, mentions: Mapping[str, str]) -> list[str]:
    """The id-like tokens :func:`resolve_references` would rewrite in ``text`` (known ids and ids no longer held)."""
    retired: frozenset[str] = getattr(mentions, "retired", frozenset())
    token, _ = _id_pattern([*mentions, *retired])
    out: list[str] = []
    for found in token.findall(text):
        if _replacement(found, mentions, retired) != found and found not in out:
            out.append(found)
    return out


def _item_phrases(item: Item) -> list[list[frozenset[str]]]:
    """The ways report text can name one item, each as a phrase: an object's name or label (or the last two words of
    what the label names, "wooden coffee table" as "coffee table", but never "on ground" from "backpack on ground"), a
    person's or animal's label or each part of its outfit. Descriptions are left out: they mention other things."""
    label = " ".join(item.label.lower().split())
    texts = [label]
    if item.kind == "entity":
        if outfit := _LABEL_OUTFIT.match(label):
            texts += [outfit[1] + part for part in outfit[2].split(" and ")]
    else:
        named = _LABEL_HEAD_END.split(f"{label} ", maxsplit=1)[0].split()
        texts += [item.name.lower(), " ".join(named[-2:]) if len(named) > 2 and "and" not in named[-2:] else ""]
    phrases = [term_sets(text) for text in dict.fromkeys(texts) if text and text not in _VAGUE_NAMES]
    return [phrase for phrase in phrases if phrase]


def _entity_head(item: Item) -> str:
    """What a person or animal is, from its label: "dog" for "black and tan dog", "man" for "man in blue shirt"."""
    words = _LABEL_HEAD_END.split(f"{item.label.lower().strip()} ", maxsplit=1)[0].split()
    return words[-1] if words else ""


def _spans(phrase: Sequence[frozenset[str]], terms: Sequence[frozenset[str]]) -> Iterable[tuple[int, int]]:
    """Each place ``phrase`` stands word for word in ``terms``, as (start, length)."""
    for start in range(len(terms) - len(phrase) + 1):
        if all(word & terms[start + n] for n, word in enumerate(phrase)):
            yield start, len(phrase)


def _named_items(text: str, view: ReportView) -> list[str]:
    """The items a piece of report text names without using their ids, in the order it names them.

    An item counts only when one of its phrases stands whole in the text; a person or animal also by its head word
    ("the dog"), when no other entity of the report has that head. The longest phrase wins a stretch of text, so
    "the white van" is not also the blue van. Items tied on one stretch are the same object if they share a name and
    label, and the first is taken; otherwise the text does not say which it means, and none is taken.
    """
    terms = term_sets(re.sub(r"\bwearing\b", "in", text.lower()))
    entities = [i for i in view.items if i.kind == "entity"]
    heads = [_entity_head(i) for i in entities]
    found: dict[tuple[int, int], list[Item]] = {}
    for item in view.items:
        phrases = _item_phrases(item)
        head = _entity_head(item) if item.kind == "entity" else ""
        if head and heads.count(head) == 1:
            phrases.append(term_sets(head))
        for span in {span for phrase in phrases for span in _spans(phrase, terms)}:
            found.setdefault(span, []).append(item)
    taken: set[int] = set()
    named: list[tuple[int, str]] = []
    for (start, length), items in sorted(found.items(), key=lambda entry: (-entry[0][1], entry[0][0])):
        stretch = set(range(start, start + length))
        if stretch & taken:
            continue
        taken |= stretch
        same_object = all(i.kind != "entity" and (i.name, i.label) == (items[0].name, items[0].label) for i in items)
        if len(items) == 1 or same_object:
            named.append((start, items[0].item_id))
    return [item_id for _, item_id in sorted(named)]


def text_items(texts: Iterable[str], view: ReportView) -> list[str]:
    """The items report texts refer to, each once, in the order they first appear: by id where a text uses ids, else
    by name (:func:`_named_items`). An item a text does not name is left out, however close it was to the action."""
    known = [i.item_id for i in view.items]
    out: list[str] = []
    seen: set[Any] = set()
    for text in texts:
        for item_id in [*referenced_ids(text, known), *_named_items(text, view)]:
            item = view.item(item_id)
            # One object can be filed twice, as an instrument and an asset; two people never count as one.
            key = item_id if item is None or item.kind == "entity" else (item.name, item.label)
            if key not in seen:
                seen.add(key)
                out.append(item_id)
    return out


@dataclass(frozen=True)
class ComposedAnswer:
    """A composed answer: the prose, the item ids it relies on (for citations), and whether the report could answer."""

    text: str
    item_ids: tuple[str, ...]
    insufficient_evidence: bool
    kind: str


def _event_sentence(event: Mapping[str, Any], mentions: Mapping[str, str]) -> str:
    body = resolve_references(str(event.get("description") or "").strip().rstrip("."), mentions)
    start, end = clock(event.get("start_seconds")), clock(event.get("end_seconds"))
    if not start:
        return f"{_capitalize(body)}."
    when = f"from {start} to {end}" if end and end != start else f"at {start}"
    return f"{_capitalize(when)}, {_lower_first(body)}."


def _event_line(event: Mapping[str, Any], mentions: Mapping[str, str]) -> str:
    """One timeline event as a list line: its time as the report gives it, then what happens."""
    body = _capitalize(resolve_references(str(event.get("description") or "").strip().rstrip("."), mentions))
    start, end = clock(event.get("start_seconds")), clock(event.get("end_seconds"))
    when = f"{start}\u2013{end}" if start and end and end != start else start
    return f"\u2022 {when} {body}." if when else f"\u2022 {body}."


def _phase(event: Mapping[str, Any], incident: Mapping[str, Any]) -> str:
    """Where an event falls around the incident window. Only an event wholly outside it is context: one that runs into
    the window is part of the incident, and an event or window with no time cannot be placed outside."""
    start = _num(event.get("start_seconds"))
    first, final = _num(incident.get("start_timestamp")), _num(incident.get("end_timestamp"))
    if start is None:
        return "during"
    end = _num(event.get("end_seconds"))
    if first is not None and (start if end is None else end) < first:
        return "before"
    return "after" if final is not None and start > final else "during"


def _timeline_lines(events: Sequence[Mapping[str, Any]], view: ReportView, mentions: Mapping[str, str]) -> list[str]:
    """The events as list lines, under before, during and after headings only when some fall outside the window."""
    phases: dict[str, list[str]] = {"before": [], "during": [], "after": []}
    for event in events:
        phases[_phase(event, view.incident)].append(_event_line(event, mentions))
    if not phases["before"] and not phases["after"]:
        return ["\n".join(phases["during"])]
    return [
        f"{heading}\n" + "\n".join(phases[phase])
        for phase, heading in (
            ("before", "Before the incident:"),
            ("during", "During the incident:"),
            ("after", "After the incident:"),
        )
        if phases[phase]
    ]


def _unknowns(view: ReportView, about: str, mentions: Mapping[str, str]) -> list[str]:
    """What the report could not establish about ``about`` (the incident as an answer tells it), as a block, or nothing.

    An uncertainty counts when it shares a word with that text beyond the words every uncertainty uses, so one about
    something the answer does not tell stays out. Each is shown once, as the report words it.
    """
    told = _words(resolve_references(about, mentions)) - _UNCERTAINTY_FILLER
    relevant: dict[str, str] = {}
    for raw in view.uncertainties:
        text = resolve_references(raw.rstrip("."), mentions)
        if _words(text) & told:
            relevant.setdefault(text.lower(), text)
    if not relevant:
        return []
    lines = [f"\u2022 {text}." for text in list(relevant.values())[:MAX_UNCERTAINTIES]]
    return ["What the report could not establish:\n" + "\n".join(lines)]


def _window(view: ReportView) -> str:
    start, end = clock(view.incident.get("start_timestamp")), clock(view.incident.get("end_timestamp"))
    if start and end and start != end:
        return f"from {start} to {end}"
    return f"at {start}" if start else ""


def _chronology(view: ReportView, targets: Sequence[Item]) -> ComposedAnswer:
    mentions = view.mentions()
    known = [i.item_id for i in view.items]
    events = list(view.timeline)
    lead_subject = ""
    if targets:
        target_ids = {t.item_id for t in targets}
        target_words = set().union(*(t.name_words for t in targets))
        about = [
            e
            for e in events
            if target_ids & set(referenced_ids(str(e.get("description") or ""), known))
            or target_words & _words(str(e.get("description") or ""))
        ]
        if about:
            events = about
            lead_subject = _join(list(dict.fromkeys(mentions[t.item_id] for t in targets)))
    kind = str(view.incident.get("type") or "").strip()
    if events:
        shown = events[:MAX_TIMELINE_EVENTS]
        if lead_subject:
            lead = f"Here is what the report records about {lead_subject}, in order:"
            blocks = [lead + "\n" + "\n".join(_event_line(e, mentions) for e in shown)]
        else:
            window = _window(view)
            lead = (
                f"The report describes {_article(kind, definite=False)}{' ' + window if window else ''}."
                if kind
                else "Here is what the report records, in order:"
            )
            told = " ".join(str(e.get("description") or "") for e in shown)
            told += f" {view.incident.get('title') or ''} {view.incident.get('description') or ''}"
            blocks = [lead, *_timeline_lines(shown, view, mentions), *_unknowns(view, told, mentions)]
        if len(events) > MAX_TIMELINE_EVENTS:
            more = _count(len(events) - MAX_TIMELINE_EVENTS, "more event", "more events")
            blocks.append(f"The timeline records {more}.")
        cited = text_items((str(e.get("description") or "") for e in shown), view)
        return ComposedAnswer("\n\n".join(blocks), tuple(cited or [t.item_id for t in targets]), False, "chronology")
    description = str(view.incident.get("description") or "").strip()
    if description:
        window = _window(view)
        text = (
            "The report has no event-by-event timeline. It describes the incident as follows: "
            f"{resolve_references(description, mentions).rstrip('.')}."
            + (f" It runs {window} in the video." if window else "")
        )
        cited = text_items([description], view)
        return ComposedAnswer(
            "\n\n".join([text, *_unknowns(view, description, mentions)]), tuple(cited), False, "chronology"
        )
    return ComposedAnswer("This report doesn't describe what happened.", (), True, "chronology")


def _people(view: ReportView, targets: Sequence[Item], *, how_many: bool) -> ComposedAnswer:
    mentions = view.mentions()
    people = [i for i in view.items if i.is_person]
    chosen = [t for t in targets if t.is_person]
    if chosen:
        details = [f"{t.introduce(mentions)}{', ' + t.seen() if t.seen() else ''}" for t in chosen]
        return ComposedAnswer(
            f"The report describes {_join(details)}.", tuple(t.item_id for t in chosen), False, "people"
        )
    if not people:
        return ComposedAnswer("This report records no people.", (), False, "people")
    details = [f"{p.introduce(mentions)}{' (' + p.seen() + ')' if p.seen() else ''}" for p in people]
    lead = _capitalize(_count(len(people), "person is", "people are"))
    text = f"{lead} involved: {_join(details)}."
    others = [i for i in view.items if i.kind == "entity" and not i.is_person]
    if others and not how_many:
        text += f" The report also records {_join([o.introduce(mentions) for o in others])}."
    cited = [p.item_id for p in people] + ([o.item_id for o in others] if others and not how_many else [])
    return ComposedAnswer(text, tuple(cited), False, "people")


def _object_phrase(view: ReportView, item: Item) -> str:
    mentions = view.mentions()
    text = item.introduce(mentions)
    holder = view.item(item.holder)
    if holder is not None:
        text += f", held by {mentions[holder.item_id]}"
    if item.threat_level is not None:
        text += f" (threat level {item.threat_level} of 5)"
    moment = item.seen()
    return f"{text}, {moment}" if moment else text


def _about(view: ReportView, targets: Sequence[Item]) -> ComposedAnswer:
    """A yes/no question about what a named item did or underwent ("did the hooded person steal anything?", "was the
    door broken?"): the report's events about it, in order, without a yes or no it does not state. With no such event
    the report does not answer it."""
    answer = _chronology(view, targets)
    if answer.kind == "chronology" and answer.text.startswith("Here is what the report records about"):
        return answer
    mentions = view.mentions()
    named = _join(list(dict.fromkeys(mentions[t.item_id] for t in targets)))
    return ComposedAnswer(
        f"The report records {named} but says nothing more about {'them' if len(targets) > 1 else 'it'} that answers "
        "this.",
        (),
        True,
        "about",
    )


def _absent(view: ReportView, unmatched: Sequence[str]) -> ComposedAnswer:
    """A question about something the report never names ("is there a dog?"): it says so, and what it does record."""
    people = [i for i in view.items if i.is_person]
    mentions = view.mentions()
    objects = list(dict.fromkeys(mentions[i.item_id] for i in view.items if i.kind != "entity"))
    text = f"This report doesn't mention {_join([chr(34) + w + chr(34) for w in unmatched])}."
    if view.items:
        text += (
            f" It records {_count(len(people), 'person', 'people')} and "
            f"{_count(len(objects), 'object', 'objects')}" + (f": {_join(objects)}." if objects else ".")
        )
    return ComposedAnswer(text, (), True, "absent")


def _holders(view: ReportView, targets: Sequence[Item]) -> ComposedAnswer | None:
    """Who held the named instruments ("who held the crowbar?"), when the report says."""
    held: list[tuple[Item, Item]] = []
    for target in targets:
        holder = view.item(target.holder) if target.kind == "instrument" else None
        if holder is not None:
            held.append((target, holder))
    if not held:
        return None
    mentions = view.mentions()
    sentences = [f"{_capitalize(mentions[t.item_id])} is held by {h.introduce(mentions)}." for t, h in held]
    cited = list(dict.fromkeys(i for t, h in held for i in (t.item_id, h.item_id)))
    return ComposedAnswer(" ".join(sentences), tuple(cited), False, "people")


def _objects(
    view: ReportView, targets: Sequence[Item], unmatched: Sequence[str], *, presence: bool, how_many: bool
) -> ComposedAnswer:
    instruments = [i for i in view.items if i.kind == "instrument"]
    assets = [i for i in view.items if i.kind == "asset"]
    chosen = [t for t in targets if t.kind != "entity"] or list(targets)
    if chosen:
        phrases = [_object_phrase(view, t) for t in chosen]
        opener = "Yes: the report records" if presence else "The report records"
        return ComposedAnswer(f"{opener} {_join(phrases)}.", tuple(t.item_id for t in chosen), False, "objects")
    sentences = []
    if unmatched and presence:
        sentences.append(f"This report doesn't mention {_join([chr(34) + w + chr(34) for w in unmatched])}.")
    if how_many:
        sentences.append(
            f"It records {_count(len(instruments), 'instrument', 'instruments')} and "
            f"{_count(len(assets), 'asset', 'assets')}."
        )
    if instruments:
        sentences.append(f"Objects used: {_join([_object_phrase(view, i) for i in instruments])}.")
    if assets:
        sentences.append(f"Property involved: {_join([_object_phrase(view, a) for a in assets])}.")
    if not instruments and not assets:
        sentences.append("It records no objects." if unmatched and presence else "This report records no objects.")
    cited = [i.item_id for i in instruments + assets]
    return ComposedAnswer(_sentence_case(" ".join(sentences)), tuple(cited), False, "objects")


def _events_about(view: ReportView, targets: Sequence[Item], pattern: re.Pattern[str] | None = None) -> list:
    """The timeline events that match ``pattern`` (any, when None) and, with targets, refer to one of them."""
    known = [i.item_id for i in view.items]
    target_ids = {t.item_id for t in targets}
    target_words = set().union(*(t.name_words for t in targets)) if targets else set()
    out = []
    for event in view.timeline:
        text = str(event.get("description") or "")
        if pattern is not None and not pattern.search(text.lower()):
            continue
        if targets and not (target_ids & set(referenced_ids(text, known)) or target_words & _words(text)):
            continue
        out.append(event)
    return out


def _taken(view: ReportView, targets: Sequence[Item]) -> ComposedAnswer:
    """What the report records being taken: its events that describe a taking, in order. With none, it says the
    report does not state that anything (or the named thing) was taken, and what it does record about it.

    A named object is what may have been taken ("was the bag stolen?"); a named person is who may have taken
    something ("did the hooded man steal anything?").
    """
    mentions = view.mentions()
    objects = [t for t in targets if t.kind != "entity"]
    focus = objects or list(targets)
    takings = _events_about(view, focus, _TAKING)
    if takings:
        shown = takings[:MAX_EVENTS]
        sentences = [_event_sentence(e, mentions) for e in shown]
        cited = text_items((str(e.get("description") or "") for e in shown), view)
        lead = "The report records this taking:" if len(shown) == 1 else "The report records these takings, in order:"
        return ComposedAnswer(" ".join([lead, *sentences]), tuple(cited or [t.item_id for t in focus]), False, "taken")
    if focus:
        named = _join(list(dict.fromkeys(mentions[t.item_id] for t in focus)))
        if objects:
            text = f"The report doesn't say {named} {'were' if len(focus) > 1 else 'was'} taken."
        else:
            text = f"The report doesn't say {named} took anything."
        about = _events_about(view, focus)[:MAX_EVENTS]
        if about:
            text += f" What it records about {named}, in order: " + " ".join(
                _event_sentence(e, mentions) for e in about
            )
        return ComposedAnswer(text, tuple(t.item_id for t in focus), True, "taken")
    text = "The report doesn't say anything was taken."
    property_ = list(dict.fromkeys(mentions[i.item_id] for i in view.items if i.kind == "asset"))
    if property_:
        text += f" The property it records is {_join(property_)}."
    return ComposedAnswer(text, (), True, "taken")


def _harm(view: ReportView) -> ComposedAnswer:
    """What could cause harm: the report's instruments (weapons and tools), most threatening first, each with its
    threat level on the report's 1-5 scale."""
    instruments = sorted((i for i in view.items if i.kind == "instrument"), key=lambda i: -(i.threat_level or 0))
    if not instruments:
        return ComposedAnswer("The report lists no weapon or other object that could cause harm.", (), False, "harm")
    phrases = [_object_phrase(view, i) for i in instruments]
    lead = _count(len(instruments), "object", "objects")
    text = f"The report lists {lead} that could be used to cause harm: {_join(phrases)}."
    if any(i.threat_level is not None for i in instruments):
        text += " Threat levels run from 1 (lowest) to 5 (highest)."
    return ComposedAnswer(text, tuple(i.item_id for i in instruments), False, "harm")


def _when(view: ReportView, targets: Sequence[Item]) -> ComposedAnswer:
    timed = [t for t in targets if t.seen()]
    if timed:
        mentions = view.mentions()
        by_mention: dict[str, list[str]] = {}
        for t in timed:  # one sentence per thing named (a till listed as instrument and asset is one thing)
            by_mention.setdefault(mentions[t.item_id], []).append(t.seen().removeprefix("seen "))
        text = " ".join(
            f"{_capitalize(m)} is seen {_join(list(dict.fromkeys(times)))}." for m, times in by_mention.items()
        )
        return ComposedAnswer(text, tuple(t.item_id for t in timed), False, "time")
    start, end = _num(view.incident.get("start_timestamp")), _num(view.incident.get("end_timestamp"))
    if start is None:
        return ComposedAnswer("This report doesn't record when the incident happens.", (), True, "time")
    if end is None or end <= start:
        return ComposedAnswer(f"The incident starts at {clock(start)} in the video.", (), False, "time")
    length = round(end - start)
    duration = f"{length} seconds" if length < 120 else f"{length // 60} minutes {length % 60} seconds"
    return ComposedAnswer(
        f"The incident runs from {clock(start)} to {clock(end)} in the video ({duration}).", (), False, "time"
    )


def _severity(view: ReportView) -> ComposedAnswer:
    level = _num(view.incident.get("severity_level"))
    if level is None:
        return ComposedAnswer("This report doesn't rate the severity.", (), True, "severity")
    band = "low" if level <= 2 else "medium" if level == 3 else "high"
    reason = str(view.incident.get("severity_reason") or "").strip().rstrip(".")
    text = f"The report rates the severity {round(level)} of 5 ({band})"
    if reason:
        text += f": {_lower_first(resolve_references(reason, view.mentions()))}"
    return ComposedAnswer(text + ".", tuple(referenced_ids(reason, [i.item_id for i in view.items])), False, "severity")


def _incident_type(view: ReportView) -> ComposedAnswer:
    kind = str(view.incident.get("type") or "").strip()
    if not kind:
        return ComposedAnswer("This report doesn't classify the incident.", (), True, "type")
    title = str(view.incident.get("title") or "").strip().rstrip(".")
    text = f"It is {_article(kind, definite=False)}" + (
        f": {resolve_references(title, view.mentions())}." if title else "."
    )
    return ComposedAnswer(text, (), False, "type")


def _chronology_asked(q: str) -> bool:
    """Whether a lower-case question asks for the course of events. "This event" only names the incident: "what
    property was involved in this event?" asks about the property."""
    return bool(_CHRONOLOGY.search(_THIS_INCIDENT.sub(" ", q)))


def _intent_words(q: str) -> set[str]:
    """The words of a lower-case question that say what kind of answer it wants, rather than what it is about."""
    return {
        w
        for pattern in (_CHRONOLOGY, _PEOPLE, _OBJECTS, _WHEN, _SEVERITY, _TYPE, _TAKEN, _HARM)
        for match in pattern.finditer(q)
        for w in _words(match.group(0))
    }


def _action_words(text: str) -> set[str]:
    # A verb's -s form is not a plural: "leaves" is "leave", which the plural rules read as "leaf".
    bases = [_PAST_FORMS.get(word, word) for word in _tokens(text)]
    return {variant for base in bases for variant in (*_variants(base), base.removesuffix("s"))}


def _block(lead: str, events: Sequence[Mapping[str, Any]], mentions: Mapping[str, str]) -> str:
    return lead + "\n" + "\n".join(_event_line(e, mentions) for e in events)


def incident_end(view: ReportView) -> float | None:
    """The second the report says the incident ends, if it says."""
    return _num(view.incident.get("end_timestamp"))


def _after_incident(view: ReportView) -> ComposedAnswer:
    """What followed the incident: the timeline's events after its window, or that the report records none."""
    mentions = view.mentions()
    after = [e for e in view.timeline if _phase(e, view.incident) == "after"]
    if not after:
        return ComposedAnswer("The report records nothing after the incident ends.", (), True, "after_incident")
    cited = text_items((str(e.get("description") or "") for e in after), view)
    return ComposedAnswer(
        _block("After the incident, the report records:", after, mentions), tuple(cited), False, "sequence"
    )


def _around(view: ReportView, q: str) -> ComposedAnswer:
    """What came after or before the moment a question points at, found by the action it names ("the man fell").

    The words that only say who ("man", or an item's name) would match most events, so they do not pick the moment.
    The first event with the action is that moment. With no such event the report does not say.
    """
    names = set().union(*(i.name_words for i in view.items)) if view.items else set()
    wanted = _action_words(_SEQUENCE.sub(" ", q)) - _intent_words(q) - names - _PEOPLE_NOUNS
    events = list(view.timeline)
    moment = next((n for n, e in enumerate(events) if wanted & _action_words(str(e.get("description") or ""))), None)
    if moment is None:
        return ComposedAnswer(
            "The report's timeline doesn't record that moment, so it can't say what came around it. "
            "Ask for the timeline of events to see everything it records.",
            (),
            True,
            "sequence",
        )
    when = clock(events[moment].get("start_seconds"))
    at = f"The report puts that moment at {when}." if when else "The report records that moment."
    side = events[:moment] if _EARLIER.search(q) else events[moment + 1 :]
    word = "Before" if _EARLIER.search(q) else "After"
    if not side:
        return ComposedAnswer(f"{at} It records nothing {word.lower()} that.", (), True, "sequence")
    if _IMMEDIATE.search(q):
        side = side[-1:] if _EARLIER.search(q) else side[:1]
    mentions = view.mentions()
    cited = text_items((str(e.get("description") or "") for e in side), view)
    return ComposedAnswer(_block(f"{at} {word} it:", side, mentions), tuple(cited), False, "sequence")


def is_plain(question: str, view: ReportView) -> bool:
    """Whether a question asks only for a kind of report field ("who appears?", "what happened?"), which a composed
    answer gives in full. One that names something, reasons, leans on the conversation or points at one moment does not.
    """
    q = _ASKS_IDS.sub(" ", question.lower())
    if _REASONING.search(q) or _CONTEXT.search(q) or _SEQUENCE.search(q) or _JUDGEMENT.search(q):
        return _AFTER_INCIDENT.search(q) is not None
    left = set(_tokens(q)) - _intent_words(q) - _PLAIN_WORDS
    return not {w for w in left if not _variants(w) & (_intent_words(q) | _PLAIN_WORDS)} and compose(
        question, view
    ).kind in (
        "chronology",
        "people",
        "objects",
        "taken",
        "harm",
        "taken-harm",
        "time",
        "severity",
        "type",
    )


def needs_context(question: str, view: ReportView) -> bool:
    """Whether a question means something only through the turns before it: "what did he do next?" names no item."""
    q = question.lower()
    return bool(_CONTEXT.search(q)) and not _named_items(question, view)


def has_no_subject(question: str, view: ReportView) -> bool:
    """Whether a question is only a pointer ("what about that one?", "what did he do?"): with no conversation before it,
    nothing says what it means."""
    q = question.lower()
    return needs_context(question, view) and not set(_tokens(_CONTEXT.sub(" ", q))) - _intent_words(q)


def compose(question: str, view: ReportView) -> ComposedAnswer:
    """The answer to one question about one report version, or a statement that the report does not say."""
    asks_ids = bool(_ASKS_IDS.search(question.lower()))
    q = _ASKS_IDS.sub(" ", question.lower())  # "the item ids of the people" asks about the people
    words = _words(q)
    known_words = set().union(
        *(i.words for i in view.items), *(_words(str(e.get("description") or "")) for e in view.timeline)
    )
    known_words |= _words(
        " ".join(str(view.incident.get(k) or "") for k in ("type", "title", "description", "location"))
    )
    intent_words = _intent_words(q)
    # Category words ("tools", "weapons") ask for every item of a kind; only other words name a particular item, and
    # an item whose name or label matches beats one whose description merely mentions the word.
    naming = words - intent_words
    targets = (
        [i for i in view.items if naming & _words(i.name)]
        or [i for i in view.items if naming & i.name_words]
        or [i for i in view.items if naming & i.words]
    )
    # The words the report never uses, as the question wrote them (a singular form that matches counts as used).
    unmatched = [
        t for t in dict.fromkeys(_tokens(q)) if not _variants(t) & known_words and not _variants(t) & intent_words
    ]
    how_many = bool(_HOW_MANY.search(q))
    people_q = bool(_PEOPLE.search(q)) and (bool(_PEOPLE_NAMED.search(q)) or not _OBJECT_KINDS.search(q))
    if _AFTER_INCIDENT.search(q):
        answer = _after_incident(view)
    elif _TIME_FIRST.search(q):
        answer = _when(view, targets)
    elif _TYPE.search(q):
        answer = _incident_type(view)
    elif _chronology_asked(q) and _SEQUENCE.search(q):
        answer = _around(view, q)
    elif _chronology_asked(q):
        answer = _chronology(view, targets)
    elif _TAKEN.search(q) or _HARM.search(q):
        # A question may ask both ("what was taken, or what could cause harm?"): each part is answered.
        parts = ([_taken(view, targets)] if _TAKEN.search(q) else []) + ([_harm(view)] if _HARM.search(q) else [])
        answer = parts[0]
        if len(parts) > 1:
            answer = ComposedAnswer(
                " ".join(part.text for part in parts),
                tuple(dict.fromkeys(i for part in parts for i in part.item_ids)),
                all(part.insufficient_evidence for part in parts),
                "taken-harm",
            )
    elif _SEVERITY.search(q) and not targets:
        answer = _severity(view)
    elif _WHEN.search(q):
        answer = _when(view, targets)
    elif _PRESENCE.search(q) and unmatched and not targets:
        answer = _absent(view, unmatched)
    elif _PRESENCE.search(q) and not _EXISTENCE.search(q) and targets:
        answer = _about(view, targets)
    elif people_q and targets and any(not t.is_person for t in targets) and (holders := _holders(view, targets)):
        answer = holders
    elif people_q and not any(not t.is_person for t in targets) and not (_OBJECTS.search(q) and unmatched):
        answer = _people(view, targets, how_many=how_many)
    elif _OBJECTS.search(q) or targets or (_PRESENCE.search(q) and unmatched):
        answer = _objects(
            view, targets, unmatched if not targets else [], presence=bool(_EXISTENCE.search(q)), how_many=how_many
        )
    else:
        about = [e for e in view.timeline if words & _words(str(e.get("description") or ""))]
        if about:
            answer = _chronology(ReportView(view.incident, view.items, tuple(about)), [])
        else:
            missing = (
                f" doesn't mention {_join([chr(34) + w + chr(34) for w in unmatched])}" if unmatched else " doesn't say"
            )
            answer = ComposedAnswer(
                f"This report{missing}. You can ask what happened, who was involved, which objects were involved, or "
                "when it happened.",
                (),
                True,
                "unanswerable",
            )
    if asks_ids and answer.item_ids:
        mentions = view.mentions()
        listed = _join([f"{i} is {mentions[i]}" for i in answer.item_ids if i in mentions])
        answer = ComposedAnswer(
            f"{answer.text} Item ids: {listed}.", answer.item_ids, answer.insufficient_evidence, answer.kind
        )
    return answer


def _incident_phrase(incident: Mapping[str, Any]) -> str:
    kind = str(incident.get("incident_type") or "").strip()
    title = str(incident.get("title") or "").strip().rstrip(".")
    phrase = _article(kind, definite=False) if kind else "an incident"
    return f'{phrase} ("{title}")' if title else phrase


def compose_hits(hits: Sequence[Mapping[str, Any]]) -> str:
    """Search hits (incident evidence items) as prose, grouped by incident, with no ids."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    incidents: dict[str, Mapping[str, Any]] = {}
    for hit in hits:
        incident = hit.get("incident") or {}
        key = str(incident.get("incident_id") or "")
        groups.setdefault(key, []).append(hit.get("item") or {})
        incidents.setdefault(key, incident)

    def item_phrase(item: Mapping[str, Any]) -> str:
        fields = (
            ("label", "name") if item.get("item_type") == "entity" else ("name", "label")
        )  # a person's type is no name
        name = next((str(item[f]) for f in fields if item.get(f)), "") or str(item.get("description") or "item")
        moment = clock(item.get("timestamp_seconds"))
        return _article(name, definite=False) + (f" (seen at {moment})" if moment else "")

    if len(groups) == 1:
        key, items = next(iter(groups.items()))
        return (
            f"I found {_count(len(items), 'matching item', 'matching items')} in "
            f"{_incident_phrase(incidents[key])}: {_join([item_phrase(i) for i in items])}."
        )
    parts = [
        f"In {_incident_phrase(incidents[k])}: {_join([item_phrase(i) for i in items])}." for k, items in groups.items()
    ]
    return " ".join([f"I found matching evidence in {_count(len(groups), 'incident', 'incidents')}.", *parts])
