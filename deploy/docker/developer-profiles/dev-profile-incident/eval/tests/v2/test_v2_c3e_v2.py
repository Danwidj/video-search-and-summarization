# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E v0.2 rules: descriptive queries, candidates, order-swapped adjudication and tiers (hermetic)."""

from __future__ import annotations

import json

import pytest

from evalv2.references import boxes
from evalv2.references import c3e_v2 as v2

STICK = {"clip": "C1", "kind": "instrument", "item_id": "I1", "query": "stick",
         "text": "stick: Long, thin wooden rod swung at E1; dropped at 5s"}
MAN = {"clip": "C1", "kind": "entity", "item_id": "E1", "query": "person", "text": "human: Man in a red shirt, running"}
A, B, C = [100, 100, 500, 400], [110, 105, 505, 410], [600, 600, 900, 900]


def test_descriptive_queries_follow_the_fixed_rule():
    assert v2.descriptive_queries(STICK) == ["long thin wooden rod swung", "stick in a hand", "a stick"]
    assert v2.descriptive_queries(MAN) == ["man in a red shirt"]


def test_union_keeps_ra1_first_and_drops_near_duplicates():
    ra1 = {2.0: [boxes.Proposal(tuple(A), 0.5, "person"), boxes.Proposal(tuple(C), 0.4, "chair")]}
    extra = {2.0: [boxes.Proposal(tuple(A), 0.3, "man in a red shirt"), boxes.Proposal(tuple(C), 0.2, "man in a red shirt"),
                   boxes.Proposal(tuple(B), 0.2, "other")]}
    out = v2.union_proposals(ra1, extra, MAN, 2.0)
    assert [p.box for p in out] == [tuple(A), tuple(C)]  # RA1 person, then the extra C; the duplicate A and "other" out


def test_candidates_merge_overlaps_and_map_the_validator_box():
    props = [boxes.Proposal(tuple(A), 0.5, "person"), boxes.Proposal(tuple(C), 0.5, "person")]
    assert v2.map_box(B, props) == A and v2.map_box([0, 0, 10, 10], props) is None
    assert v2.candidates(A, B, C) == [A, C]


def _adj(choice_a, choice_b, conf=0.8):
    packets = v2.box_adjudication_packets(MAN, 4, [A, C], "adj")
    num = {name: {tuple(b): n for n, b in p["marks"].items()} for name, p in packets.items()}
    pick = lambda name, c: num[name][tuple(c)] if isinstance(c, list) else c  # noqa: E731
    return {name: (packets[name], {"answer": {"choice": pick(name, c), "confidence": conf}})
            for name, c in (("a", choice_a), ("b", choice_b))}


def test_adjudication_orders_are_reversed_and_hide_sources():
    packets = v2.box_adjudication_packets(MAN, 4, [A, C], "adj")
    assert list(packets["a"]["marks"].values()) == list(reversed(list(packets["b"]["marks"].values())))
    text = json.dumps(packets)
    assert "generator" not in text and "validator" not in text and "predict" not in text


def test_box_tiers():
    assert v2.resolve_box(A, B, None, True)["tier"] == "consensus"
    assert v2.resolve_box(None, None, None, False)["reason"] == "no candidate box"
    assert v2.resolve_box(A, C, None, True)["tier"] == "pending"
    assert v2.resolve_box(A, C, _adj(C, C), True) == {"tier": "adjudicated", "box": C, "visible": True}
    assert v2.resolve_box(A, C, _adj(A, C), True)["reason"] == "adjudicator inconsistent across orders"
    assert v2.resolve_box(A, C, _adj(A, A, conf=0.5), True)["reason"] == "adjudicator confidence below 0.6"
    assert v2.resolve_box(A, C, _adj("not_visible", "not_visible"), True)["visible"] is False
    assert v2.resolve_box(A, C, _adj("cannot_identify", "cannot_identify"), True)["tier"] == "unresolved"
    with pytest.raises(v2.C3EV2Error):
        v2.resolve_box(A, C, {"a": _adj(A, A)["a"], "b": (_adj(A, A)["b"][0], {"answer": {"choice": 9}})}, True)


def test_visibility_consensus_needs_a_neighbour_of_the_other_pass():
    gen, val = {0: "no", 2: "yes", 4: "unclear"}, {1: "no", 3: "yes", 5: "yes"}
    assert v2.visibility_consensus(gen, val, 2) == "yes" and v2.visibility_consensus(gen, val, 1) == "no"
    assert v2.visibility_consensus(gen, val, 4) is None
    assert v2.visibility_consensus({0: "yes"}, {1: "no"}, 0) is None


def test_visibility_adjudication_selects_sampled_seconds_first_and_resolves_by_both_orders():
    gen = {s: "unclear" for s in range(0, 40, 2)}
    val = {s: "unclear" for s in range(1, 40, 2)}
    seconds = v2.visibility_adjudication_seconds(gen, val, 39, sampled=[7, 31])
    assert 7 in seconds and 31 in seconds and len(seconds) == 12
    packets = v2.visibility_adjudication_packets(MAN, seconds, "vadj")
    assert all(len(s["tiles"]) <= 4 for s in packets["a"]["sheets"])
    answers = {name: {"answers": [{"t": t, "visible": "yes" if t != 7.0 else ("yes" if name == "a" else "no"),
                                   "confidence": 0.9} for s in p["sheets"] for t in s["tiles"]]}
               for name, p in packets.items()}
    out = v2.visibility_adjudicated(packets, answers)
    assert out[31] == {"tier": "adjudicated", "visible": "yes"}
    assert out[7]["reason"] == "adjudicator inconsistent across orders"


def test_visibility_state_precedence():
    gen, val = {2: "yes"}, {1: "yes", 3: "yes"}
    assert v2.visibility_state(2, gen, val, None, {})["tier"] == "consensus"
    assert v2.visibility_state(5, gen, val, {"tier": "consensus"}, {})["source"] == "box passes agree"
    assert v2.visibility_state(5, gen, val, None, {5: {"tier": "adjudicated", "visible": "no"}})["visible"] is False
    assert v2.visibility_state(5, gen, val, {"tier": "adjudicated", "visible": True}, {})["tier"] == "adjudicated"
    assert v2.visibility_state(5, gen, val, None, {})["tier"] == "unresolved"
