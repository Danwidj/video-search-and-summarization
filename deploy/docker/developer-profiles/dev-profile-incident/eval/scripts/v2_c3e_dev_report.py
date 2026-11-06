# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E v0.2 development report (offline, read-only on the run directory): C1b Nano and Super against the
AI-referenced development references. DEVELOPMENT, AI-REFERENCED: not held-out and not human-verified.

    uv run --frozen python scripts/v2_c3e_dev_report.py OUT.json --run RUN_DIR --c3e DIR [--notes NOTES.json]

The scorer is ``evalv2.references.c3e_score`` (v0.2) unchanged; this script only tabulates.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

from evalv2.references import c3e_score as cs  # noqa: E402

TIER_SETS = {"consensus_only": {"consensus"}, "adjudicated_only": {"adjudicated"},
             "combined": {"consensus", "adjudicated"}}
KINDS = ("entity", "instrument", "asset")
SEED, N = 20261027, 10000


def _rate(rows, hit):
    n = len(rows)
    return {"n": n, "k": sum(1 for r in rows if hit(r)), "value": round(sum(1 for r in rows if hit(r)) / n, 4) if n else None}


def _ci(rows, hit):
    per = defaultdict(list)
    for r in rows:
        per[r["clip"]].append((1.0 if hit(r) else 0.0, 1.0))
    return cs._boot(per) if rows else None


def cell(rows, tiers):
    """One subject x kind cell: population, coverage and the conditional metrics on one tier set."""
    matched = [r for r in rows if r["class"] != "unmatched_item"]
    entries = [r for r in rows if r["class"] != "missing_evidence"]
    judged = [r for r in matched if r["class"] in cs.JUDGED and r["tier"] in tiers]
    timing = [r for r in matched if r["tier"] in tiers and r["class"] in ("correct", "spatial_miss", "temporal_miss",
                                                                          "unscorable_iou")]
    box_scorable = [r for r in matched if r["tier"] in tiers and r["class"] in ("correct", "spatial_miss")]
    ious = sorted(r["iou"] for r in box_scorable)
    correct = lambda r: r["class"] == "correct"  # noqa: E731
    return {
        "predicted_entries": len(entries),
        "unmatched_entries": sum(1 for r in rows if r["class"] == "unmatched_item"),
        "missing_evidence_items": sum(1 for r in rows if r["class"] == "missing_evidence"),
        "entries_with_box_reference": len(box_scorable),
        "entries_with_timing_reference": len(timing),
        "unresolved_or_unscorable": sum(1 for r in matched if r["class"].startswith("unscorable")
                                        and r["class"] != "unscorable_iou"),
        "not_located": sum(1 for r in judged if r["class"] == "not_located"),
        "iou_median": ious[len(ious) // 2] if ious else None,
        "iou_ge_0_5_given_box_reference": _rate(box_scorable, lambda r: r["iou"] >= 0.5),
        "correct_evidence_conditional": {**_rate(judged, correct), "ci95": _ci(judged, correct)},
        "correct_evidence_over_all_matched": _rate(matched, correct),
        "temporal_alignment_conditional": {**_rate(timing, lambda r: r["class"] != "temporal_miss"),
                                           "ci95": _ci(timing, lambda r: r["class"] != "temporal_miss")},
    }


def paired(rows, a, b, tiers):
    """Nano - Super difference in pooled correct-evidence rate, clips resampled jointly (clips with judged entries for
    both); two-sided bootstrap p."""
    def judged(s):
        return [r for r in rows if r["subject"] == s and r["class"] in cs.JUDGED and r["tier"] in tiers]
    ja, jb = judged(a), judged(b)
    clips = sorted({r["clip"] for r in ja} & {r["clip"] for r in jb})
    by = lambda js: {c: [1.0 if r["class"] == "correct" else 0.0 for r in js if r["clip"] == c] for c in clips}  # noqa: E731
    pa, pb = by(ja), by(jb)

    def diff(cs_):
        xa = [v for c in cs_ for v in pa[c]]
        xb = [v for c in cs_ for v in pb[c]]
        return sum(xa) / len(xa) - sum(xb) / len(xb)
    if len(clips) < 2:
        return {"clips": len(clips), "note": "too few clips for a paired estimate"}
    point = diff(clips)
    rnd = random.Random(SEED)
    samples = sorted(diff([clips[rnd.randrange(len(clips))] for _ in clips]) for _ in range(N))
    p = min(1.0, 2 * min(sum(s <= 0 for s in samples), sum(s >= 0 for s in samples)) / N)
    return {"clips": len(clips), "entries": [sum(len(pa[c]) for c in clips), sum(len(pb[c]) for c in clips)],
            "diff": round(point, 4), "ci95": [round(samples[int(.025 * N)], 4), round(samples[int(.975 * N) - 1], 4)],
            "p_two_sided": round(p, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--c3e", type=Path, required=True)
    ap.add_argument("--notes", type=Path, default=Path("/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0-c3e-notes-v1.json"))
    a = ap.parse_args()
    vis = json.loads((a.c3e / "tiers/dev/visibility-tiers.json").read_text())
    box = json.loads((a.c3e / "tiers/dev/box-tiers.json").read_text())
    notes = json.loads(a.notes.read_text())["notes"]
    identity = [f"{n['clip']}-{i}" for n in notes if n["affects_identity"] for i in n["items"]]
    all_noted = [f"{n['clip']}-{i}" for n in notes for i in n["items"]]
    out = {"label": "DEVELOPMENT (C1b, 25 dev clips), AI-REFERENCED (C3-E v0.2): not held-out, not human-verified",
           "historical_profile": "agent acbf892ba, tracking off: not production", "by_threshold": {}}
    for t in (0.3, 0.5, 0.7):
        rows = cs.score_runs_v2([a.run], vis, box, identity, iou_threshold=t)
        block = {"summary": cs.summarise_v2(rows), "cells": {}, "paired_nano_minus_super": {}}
        for subject in sorted({r["subject"] for r in rows}):
            mine = [r for r in rows if r["subject"] == subject]
            block["cells"][subject] = {name: {k: cell([r for r in mine if r["kind"] == k], tiers) for k in KINDS + ("all",)}
                                       if False else {**{k: cell([r for r in mine if r["kind"] == k], tiers) for k in KINDS},
                                                      "all": cell(mine, tiers)}
                                       for name, tiers in TIER_SETS.items()}
            block["cells"][subject]["classes"] = dict(Counter(r["class"] for r in mine))
            block["cells"][subject]["unscorable_reasons"] = dict(Counter(r["reason"] for r in mine
                                                                         if r["class"].startswith("unscorable")))
        for name, tiers in TIER_SETS.items():
            block["paired_nano_minus_super"][name] = paired(rows, "nano-pipeline", "super-pipeline", tiers)
        out["by_threshold"][str(t)] = block
        if t == 0.5:
            out["rows_at_0_5"] = rows
    excl = cs.score_runs_v2([a.run], vis, box, all_noted, iou_threshold=0.5)
    out["sensitivity_exclude_all_noted_items"] = {s: cell([r for r in excl if r["subject"] == s], TIER_SETS["combined"])
                                                  for s in sorted({r["subject"] for r in excl})}
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(a.out), "rows": len(out["rows_at_0_5"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
