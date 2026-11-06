# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E v0.2 evaluation-half report (offline, read-only on the runs): same tabulation as the frozen development report.

    uv run --frozen python scripts/v2_c3e_test_report.py OUT.json --run RUN_DIR [--run RUN_DIR ...] --c3e DIR

Imports `cell` and `paired` from `scripts/v2_c3e_dev_report.py` unchanged and scores with `c3e_score` v0.2 unchanged;
only the tier directory (`tiers/test`) and the label differ. Each run is scored and reported on its own, so the
original C3 and contingency subjects are never pooled. A paired Nano - Super estimate is produced only for a run
holding both subjects.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("c3e_dev_report", HERE / "v2_c3e_dev_report.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
cs = dev.cs


def run_block(run: Path, vis: dict, box: dict, identity: list, all_noted: list) -> dict:
    out: dict = {"run": run.name, "by_threshold": {}}
    for t in (0.3, 0.5, 0.7):
        rows = cs.score_runs_v2([run], vis, box, identity, iou_threshold=t)
        block: dict = {"summary": cs.summarise_v2(rows), "cells": {}}
        subjects = sorted({r["subject"] for r in rows})
        for subject in subjects:
            mine = [r for r in rows if r["subject"] == subject]
            block["cells"][subject] = {name: {**{k: dev.cell([r for r in mine if r["kind"] == k], tiers) for k in dev.KINDS},
                                              "all": dev.cell(mine, tiers)} for name, tiers in dev.TIER_SETS.items()}
            block["cells"][subject]["classes"] = dict(Counter(r["class"] for r in mine))
            block["cells"][subject]["unscorable_reasons"] = dict(Counter(r["reason"] for r in mine
                                                                         if r["class"].startswith("unscorable")))
        if {"nano-pipeline", "super-pipeline"} <= set(subjects):
            block["paired_nano_minus_super"] = {name: dev.paired(rows, "nano-pipeline", "super-pipeline", tiers)
                                                for name, tiers in dev.TIER_SETS.items()}
        out["by_threshold"][str(t)] = block
        if t == 0.5:
            out["rows_at_0_5"] = rows
    excl = cs.score_runs_v2([run], vis, box, all_noted, iou_threshold=0.5)
    out["sensitivity_exclude_all_noted_items"] = {s: dev.cell([r for r in excl if r["subject"] == s], dev.TIER_SETS["combined"])
                                                  for s in sorted({r["subject"] for r in excl})}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--run", type=Path, action="append", required=True)
    ap.add_argument("--c3e", type=Path, required=True)
    ap.add_argument("--notes", type=Path, default=Path("/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0-c3e-notes-v1.json"))
    a = ap.parse_args()
    vis = json.loads((a.c3e / "tiers/test/visibility-tiers.json").read_text())
    box = json.loads((a.c3e / "tiers/test/box-tiers.json").read_text())
    notes = json.loads(a.notes.read_text())["notes"]
    identity = [f"{n['clip']}-{i}" for n in notes if n["affects_identity"] for i in n["items"]]
    all_noted = [f"{n['clip']}-{i}" for n in notes for i in n["items"]]
    out = {"label": "EVALUATION HALF (55 previously exposed clips), AI-REFERENCED (C3-E v0.2): not human-verified",
           "historical_profile": "agent acbf892ba, tracking off: not production",
           "runs": [run_block(r, vis, box, identity, all_noted) for r in a.run]}
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(a.out), "rows": {b["run"]: len(b["rows_at_0_5"]) for b in out["runs"]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
