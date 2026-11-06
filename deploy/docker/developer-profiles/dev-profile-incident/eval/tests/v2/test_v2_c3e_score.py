# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E scoring: J5 through the stored matching, one class per entry, missing evidence, tiers apart (hermetic)."""

from __future__ import annotations

import json

from evalv2.references import c3e_score

BOX = [100.0, 100.0, 500.0, 400.0]


def _run(tmp_path):
    run = tmp_path / "run"
    digest = "ab" + "c" * 62
    obj = run / "store" / "objects" / "pipeline-prediction" / digest[:2]
    obj.mkdir(parents=True)
    evidence = [
        {"item_type": "entity", "item_id": "E1", "box_seconds": 4, "located": True, "bounding_box": BOX,
         "detected_box": BOX},
        {"item_type": "entity", "item_id": "E2", "box_seconds": 9, "located": True, "bounding_box": BOX,
         "detected_box": BOX},
        {"item_type": "asset", "item_id": "A1", "box_seconds": 3, "located": None, "bounding_box": None,
         "image_gap": "crop-call cap reached: crop-call cap of 40"},
        {"item_type": "entity", "item_id": "E9", "box_seconds": 2, "located": True, "bounding_box": BOX,
         "detected_box": BOX}]
    (obj / f"{digest}.json").write_text(json.dumps({"payload": {"evidence": evidence}}))
    (run / "checkpoint.jsonl").write_text(json.dumps({"subject": "nano-pipeline", "item_id": "C1", "repeat": 1,
                                                      "prediction_ref": f"pipeline-prediction:{digest}"}) + "\n")
    scoring = run / "scoring" / "evalv2-score-stage-v3" / "primary"
    scoring.mkdir(parents=True)
    row = {"stage": "final", "subject": "nano-pipeline", "incident_id": "C1", "repeat": 1, "outcome": "scored",
           "entities": {"matches": [{"entity_id": "E1", "gt_entity_id": "E1"}, {"entity_id": "E2", "gt_entity_id": "E2"},
                                    {"entity_id": "E3", "gt_entity_id": "E3"}]},
           "instruments": {"matches": []}, "assets": {"matches": [{"asset_id": "A1", "gt_asset_id": "A1"}]}}
    (scoring / "live-videos.jsonl").write_text(json.dumps(row) + "\n")
    return run


def _record(item, tier, boxes, spans):
    rec = {"record_id": f"box:C1:{item}", "dataset": "d", "kind": "box", "clip": "C1", "strata": {}, "flags": [],
           "provenance": {}, "tier": tier, "human": None,
           "payload": {"clip": "C1", "kind": "asset" if item.startswith("A") else "entity", "item_id": item,
                       "boxes": boxes, "visible_spans": spans}}
    return rec


def test_classes_missing_evidence_and_tiers(tmp_path):
    run = _run(tmp_path)
    records = [_record("E1", "ai_validated", {"4": BOX}, [[2, 6]]),
               _record("E2", "ai_validated", {"4": BOX}, [[2, 6]]),
               _record("E3", "ai_validated", {}, [[0, 3]]),
               _record("A1", "ai_proposed", {}, [[0, 9]])]
    rows = c3e_score.score_runs([run], records)
    by = {(r["gt_item_id"] or "unmatched", r["class"]) for r in rows}
    assert ("E1", "correct") in by and ("E2", "temporal_miss") in by and ("E3", "missing_evidence") in by
    assert ("A1", "unscorable") in by and ("unmatched", "unmatched_item") in by
    report = c3e_score.report(rows)["nano-pipeline"]
    assert report["verified"]["correct_evidence_rate"]["n"] == 0  # nothing human-verified: no primary result
    provisional = report["provisional_ai_validated"]
    assert provisional["correct_evidence_rate"]["n"] == 2 and provisional["correct_evidence_rate"]["value"] == 0.5
    assert report["unscorable_reasons"] == {"crop-call cap reached: crop-call cap of 40": 1}
    assert provisional["by_kind"]["entity"]["counts_only"]  # under 20 scorable entries: counts only


def test_v2_classes_tiers_threshold_and_bounds():
    e = {"item_type": "entity", "item_id": "E1", "box_seconds": 4, "located": True, "bounding_box": BOX, "detected_box": BOX}
    vis_yes = {"tier": "consensus", "visible": True}
    near = [110.0, 110.0, 520.0, 420.0]
    c = c3e_score.classify_v2
    assert c(e, vis_yes, {"tier": "adjudicated", "box": BOX})["class"] == "correct"
    assert c(e, vis_yes, {"tier": "adjudicated", "box": BOX})["tier"] == "adjudicated"
    assert c(e, {"tier": "unresolved"}, None)["reason"] == "visibility unresolved at that second"
    assert c(e, {"tier": "adjudicated", "visible": False}, None)["class"] == "temporal_miss"
    assert c(e, vis_yes, {"tier": "unresolved", "reason": "cannot identify", "box": None})["class"] == "unscorable_iou"
    assert c(dict(e, located=False, bounding_box=None), vis_yes, None)["class"] == "not_located"
    assert c(e, vis_yes, {"tier": "consensus", "box": near}, iou_threshold=0.9)["class"] == "spatial_miss"
    assert c(e, vis_yes, {"tier": "consensus", "box": BOX}, identity_flagged=True)["class"] == "unscorable"
    rows = [{"subject": "s", "clip": "C1", "kind": "entity", "class": "correct", "tier": "consensus", "iou": 1.0},
            {"subject": "s", "clip": "C2", "kind": "entity", "class": "spatial_miss", "tier": "adjudicated", "iou": 0.2},
            {"subject": "s", "clip": "C3", "kind": "entity", "class": "unscorable", "reason": "x", "tier": None}]
    out = c3e_score.summarise_v2(rows)["s"]
    assert out["combined"]["correct_evidence"]["value"] == 0.5 and out["combined"]["coverage"]["share"] == round(2 / 3, 4)
    assert out["consensus_only"]["correct_evidence"]["value"] == 1.0
    assert out["bounds_unresolved"]["worst"] == round(1 / 3, 4) and out["bounds_unresolved"]["best"] == round(2 / 3, 4)
