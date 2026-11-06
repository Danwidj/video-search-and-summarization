# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E review: proposals, assignment, the human_verified tier and reviewer agreement (hermetic)."""

from __future__ import annotations

import pytest

from evalv2.references import c3e_review as cr

ITEM = {"clip": "C1", "kind": "entity", "item_id": "E1", "text": "man in red"}
A, B = [100, 100, 500, 400], [110, 105, 505, 410]


def _item():
    return cr.proposals(ITEM, {"visible_spans": [[2, 6]], "flags": ["unclear"]},
                        {2: A, 4: A, 6: None}, {2: B, 4: [700, 700, 900, 900], 6: None}, [6, 2, 4])


def test_proposals_are_sorted_unlabelled_and_flag_disagreements():
    item = _item()
    assert [r["second"] for r in item["boxes"]] == [2, 4, 6]
    assert [r["status"] for r in item["boxes"]] == ["agree", "disagree", "none_fits"]
    assert {"box_disagreement", "none_fits", "unclear"} <= set(item["flags"])
    assert "anchor" not in str(item) and "decoy" not in str(item)
    assert "no_interval_proposal" in cr.proposals(ITEM, None, {}, {}, [])["flags"]


def test_assignment_needs_two_reviewers_and_never_gives_a_second_review_to_the_primary():
    items = [{"key": f"C{c}-E{i}", "clip": f"C{c}", "kind": "entity", "half": "dev", "category": "Assault"}
             for c in range(6) for i in range(3)]
    with pytest.raises(cr.ReviewError):
        cr.assign(items, ["R1"])
    config = cr.assign(items, ["R1", "R2", "R3"])
    assert config == cr.assign(items, ["R1", "R2", "R3"])
    assert len(config["second"]) == 2  # ceil(10% of 18)
    for key, reviewer in config["second"].items():
        assert reviewer != config["primary"][key.split("-")[0]]


def _record():
    from evalv2.datasets.records import new_record

    return new_record(record_id="box:C1:E1", dataset="box-references-c3e-dev-v1", kind="box",
                      payload={"clip": "C1", "kind": "entity", "item_id": "E1", "boxes": {"2": A},
                               "visible_spans": [[2, 6]]}, clip="C1", generator={"model": "m", "prompt": "p"})


def test_a_review_is_verified_only_when_every_frame_is_decided():
    from evalv2.datasets.records import RecordError, effective_payload, validate_record

    item, record = _item(), _record()
    partial = {"reviewer": "team-member-1", "at": "2026-11-05T10:00:00+08:00", "visible_spans": [[2, 5]],
               "boxes": [{"second": 2, "decision": "accept"}]}
    with pytest.raises(cr.ReviewError):
        cr.apply_review(record, item, partial, source_sha256="x")
    bad_accept = dict(partial, boxes=[{"second": 2, "decision": "accept"}, {"second": 4, "decision": "accept"},
                                      {"second": 6, "decision": "accept"}])
    assert any("no proposed box" in p for p in cr.check_review(bad_accept, item))
    full = dict(partial, boxes=[{"second": 2, "decision": "accept"},
                                {"second": 4, "decision": "redraw", "box": [120, 100, 480, 390]},
                                {"second": 6, "decision": "reject_not_visible"}])
    out = cr.apply_review(record, item, full, source_sha256="x")
    assert out["tier"] == "human_verified" and out["human"]["reviewer"] == "team-member-1"
    assert out["human"]["decision"] == "edit" and validate_record(out) == []
    payload = effective_payload(out)
    assert payload["boxes"] == {"2": A, "4": [120, 100, 480, 390]}
    assert payload["rejected_seconds"] == {"6": "reject_not_visible"} and payload["visible_spans"] == [[2, 5]]
    assert record["tier"] == "ai_proposed"  # the AI record is never modified in place
    with pytest.raises(RecordError):  # only people verify
        cr.apply_review(record, item, dict(full, reviewer="claude-opus"), source_sha256="x")


def test_agreement_reports_kappa_boundaries_and_box_iou():
    item = _item()
    p = {"visible_spans": [[2, 6]], "boxes": [{"second": 2, "decision": "accept"},
                                              {"second": 4, "decision": "redraw", "box": A},
                                              {"second": 6, "decision": "reject_not_visible"}]}
    s = {"visible_spans": [[3, 6]], "boxes": [{"second": 2, "decision": "redraw", "box": B},
                                              {"second": 4, "decision": "reject_not_identifiable"},
                                              {"second": 6, "decision": "reject_not_visible"}]}
    out = cr.agreement({item["key"]: item}, {item["key"]: p}, {item["key"]: s}, {"C1": 9})
    assert out["items"] == 1 and out["boundaries_within_1s"] == 1 and out["box_pairs"] == 1
    assert out["box_iou_median"] > 0.9 and out["seconds"] == 10
    assert cr.kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0 and cr.kappa([1, 1], [1, 1]) is None
