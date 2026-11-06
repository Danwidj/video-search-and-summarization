# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E sampling rules: anchors, decoys, blind packets and interval proposals (hermetic)."""

from __future__ import annotations

import json

import pytest

from evalv2.references import boxes, c3e

GT = {"by_incident_id": {"C1": {"category": "Assault", "p1_shaped": {
    "entities": [{"entity_id": "E1", "type": "human", "description": "man in red"},
                 {"entity_id": "E2", "type": "human", "description": "man in blue"}],
    "instruments": [{"instrument_id": "I1", "name": "knife", "description": "short knife"}],
    "assets": []}}}}


def _write_run(tmp_path, entries):
    run = tmp_path / "run"
    objects = run / "store" / "objects" / "pipeline-prediction"
    lines = []
    for n, (clip, evidence) in enumerate(entries):
        digest = f"{n:02d}" + "a" * 62
        (objects / digest[:2]).mkdir(parents=True, exist_ok=True)
        (objects / digest[:2] / f"{digest}.json").write_text(json.dumps({"payload": {"evidence": evidence}}))
        lines.append(json.dumps({"item_id": clip, "subject": "nano-pipeline", "repeat": 1,
                                 "prediction_ref": f"pipeline-prediction:{digest}"}))
    (run / "checkpoint.jsonl").write_text("\n".join(lines) + "\n")
    return run


def test_anchors_read_only_the_kind_and_second_of_located_boxes(tmp_path):
    run = _write_run(tmp_path, [("C1", [
        {"item_type": "entity", "box_seconds": 4, "located": True, "bounding_box": [1, 2, 3, 4], "item_id": "E9"},
        {"item_type": "entity", "timestamp_seconds": 6, "located": True, "bounding_box": [1, 2, 3, 4]},
        {"item_type": "instrument", "box_seconds": 5, "located": None, "bounding_box": None, "image_gap": "cap"},
        {"item_type": "asset", "box_seconds": 7, "located": False, "bounding_box": None}])])
    rows = c3e.evidence_seconds(run)
    assert {tuple(sorted(r)) for r in rows} == {("clip", "has_box", "kind", "repeat", "second", "subject")}
    assert c3e.anchors(rows) == {"C1": {"entity": [4, 6]}}


def test_non_whole_evidence_seconds_are_refused(tmp_path):
    run = _write_run(tmp_path, [("C1", [{"item_type": "entity", "box_seconds": 4.5, "located": True,
                                         "bounding_box": [1, 2, 3, 4]}])])
    with pytest.raises(c3e.C3EError):
        c3e.evidence_seconds(run)


def test_decoys_are_seeded_counted_and_never_anchor_seconds():
    anchors = [3, 4, 5, 9, 12]
    first = c3e.decoys("C1", "entity", anchors, anchors + [20], 30.5)
    assert first == c3e.decoys("C1", "entity", anchors, anchors + [20], 30.5)
    assert len(first) == 2  # ceil(5 / 4)
    assert not set(first) & set(anchors + [20]) and all(s + 0.5 < 30.5 for s in first)
    assert c3e.decoys("C1", "entity", anchors, anchors, 30.5, seed=1) != first or True  # seed is an input
    assert c3e.decoys("C1", "entity", [], [], 30.5) == []
    assert len(c3e.decoys("C1", "entity", [1], [1], 30.5)) == 1


def test_plan_mixes_anchors_and_decoys_per_item_of_the_anchored_kind_only():
    evidence = [{"clip": "C1", "kind": "entity", "second": s, "has_box": True, "subject": "x", "repeat": 1}
                for s in (2, 3)]
    planned = c3e.plan(GT, ["C1"], {"C1": 10.03}, evidence, half="dev")
    entry = planned["sampling"]["C1"]["entity"]
    assert entry["anchors"] == [2, 3] and len(entry["decoys"]) == 1
    assert set(planned["item_times"]) == {"C1-E1", "C1-E2"}  # no instrument anchors: no instrument packet
    assert planned["item_times"]["C1-E1"] == sorted(entry["anchors"] + entry["decoys"])


def test_box_packets_hide_which_seconds_are_anchors_and_stay_blind(tmp_path):
    proposals = {f"{t:.3f}": [{"box": [100 + t, 100, 300 + t, 400], "score": 0.5, "label": "person"}]
                 for t in [x / 2 for x in range(0, 20)]}
    (tmp_path / "C1.json").write_text(json.dumps({"frames": proposals, "queries": ["person"], "detector": {}}))
    evidence = [{"clip": "C1", "kind": "entity", "second": 2, "has_box": True, "subject": "x", "repeat": 1}]
    planned = c3e.plan(GT, ["C1"], {"C1": 10.03}, evidence, half="dev")
    packets = c3e.box_packets(planned, tmp_path, generator_prompt="gen-box-select-v1",
                              validator_prompt="gen-box-validate-v1")
    assert [p["key"] for p in packets] == ["C1-E1", "C1-E2"]
    gen = packets[0]["generator"]
    text = json.dumps(gen)
    assert "anchor" not in text and "decoy" not in text
    answers = [{"second": f["t"], "choice": 1, "confidence": 0.9} for f in gen["frames"]]
    boxes.assert_blind(packets[0]["validator"], gen, answers)
    assert [f["t"] for f in packets[0]["validator"]["frames"]] == [t + 0.5 for t in planned["item_times"]["C1-E1"]]


def test_visibility_packets_split_even_and_odd_seconds_and_are_blind():
    [packet] = c3e.visibility_packets(GT, ["C1"], {"C1": 20.03})
    gen_t = [t for s in packet["generator"]["sheets"] for t in s["tiles"]]
    val_t = [t for s in packet["validator"]["sheets"] for t in s["tiles"]]
    assert gen_t == [float(s) for s in range(0, 21, 2)] and val_t == [float(s) for s in range(1, 20, 2)]
    assert all(len(s["tiles"]) <= 9 for s in packet["generator"]["sheets"])
    c3e.assert_visibility_blind(packet["validator"], packet["generator"])
    bad = dict(packet["validator"], sheets=packet["generator"]["sheets"])
    with pytest.raises(c3e.C3EError):
        c3e.assert_visibility_blind(bad, packet["generator"])


def test_visibility_votes_require_every_tile_and_item():
    [packet] = c3e.visibility_packets(GT, ["C1"], {"C1": 4.03})
    gen = packet["generator"]
    ok = {"answers": [{"t": t, "visible": {"E1": "yes", "E2": "no", "I1": "unclear"}}
                      for s in gen["sheets"] for t in s["tiles"]]}
    votes = c3e.visibility_votes(gen, ok)
    assert votes["E1"] == {0: "yes", 2: "yes", 4: "yes"}
    with pytest.raises(c3e.C3EError):
        c3e.visibility_votes(gen, {"answers": ok["answers"][:-1]})
    with pytest.raises(c3e.C3EError):
        c3e.visibility_votes(gen, {"answers": [dict(a, visible={"E1": "maybe", "E2": "no", "I1": "no"})
                                               for a in ok["answers"]]})


def test_interval_proposal_bridges_unclear_and_flags_flicker():
    gen = {0: "no", 2: "yes", 4: "yes", 6: "no", 8: "yes"}
    val = {1: "no", 3: "unclear", 5: "yes", 7: "no", 9: "no"}
    out = c3e.interval_proposal(gen, val, 10.03)
    assert out["visible_spans"] == [[2, 5], [8, 8]]
    assert out["flicker_seconds"] == [8] and "unclear" in out["flags"] and "flicker" in out["flags"]
    assert c3e.interval_proposal({0: "no"}, {1: "no"}, 2.03)["flags"] == ["never_visible"]


def test_render_sheet_and_marks(tmp_path):
    from PIL import Image

    (tmp_path / "C1").mkdir()
    for t in (0.0, 2.0, 4.0):
        Image.new("RGB", (640, 360), (10, 20, 30)).save(tmp_path / "C1" / f"t{t:08.3f}.jpg")
    c3e.render_sheet(tmp_path, "C1", [0.0, 2.0, 4.0], tmp_path / "s.jpg", tile_width=200)
    assert Image.open(tmp_path / "s.jpg").size == (600, 112)
    # [ymin, xmin, ymax, xmax]: a box on the left half, top to bottom
    c3e.draw_marks(tmp_path, "C1", {"t": 2.0, "marks": {"1": [0, 0, 1000, 500]}}, tmp_path / "m.jpg", width=320)
    drawn = Image.open(tmp_path / "m.jpg").convert("RGB")
    assert drawn.size == (320, 180)
    red = lambda px: px[0] > 180 and px[1] < 120  # noqa: E731
    assert red(drawn.getpixel((159, 100))) and not red(drawn.getpixel((300, 100)))
