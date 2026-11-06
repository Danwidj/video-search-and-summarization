# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Object scores under each denominator (offline). Stored counts only; thresholds and matching unchanged.

    python3 scripts/v2_object_views.py OUT.csv

valid_only: scored rows. mixed_chart: scored rows plus invalid outputs as empty reports, no-output runs dropped (the
continuity view the original D2 chart used). end_to_end: every planned run, failures and unsent items as empty reports.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

R = Path("/home/hengz/evalv2-data/v2/runs")
TAIL = "scoring/evalv2-score-stage-v3/primary/live-videos.jsonl"
KINDS = ("entities", "instruments", "assets")
MO = ("scored", "contract_invalid", "parse_failure")
SW = ("c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a", "c3-track-a-switchyard-recovery-a5s")
GROUPS = {"nano-direct": SW, "omni-direct": SW, "super-direct": SW, "gemma4-31b-openrouter": ("c3-track-a-openrouter",),
          "qwen35-9b-openrouter": ("c3-track-a-openrouter",)}


def f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def rows_for(subject: str) -> dict:
    best: dict = {}
    for run in GROUPS[subject]:
        for line in (R / run / TAIL).read_text().splitlines():
            r = json.loads(line)
            if r["subject"] != subject or r.get("stage", "p1") != "p1":
                continue
            k = (r["incident_id"], r["repeat"])
            if k not in best or best[k]["outcome"] not in MO:
                best[k] = r
    return best


def score(valid: list, empty_gt: list) -> dict:
    c = {k: [0, 0, 0] for k in KINDS}
    for r in valid:
        for k in KINDS:
            x = r[k]["counts"]
            c[k][0] += x["tp"]
            c[k][1] += x["fp"]
            c[k][2] += x["fn"]
    for gt in empty_gt:
        for k in KINDS:
            c[k][2] += gt[k]
    obj = [c["instruments"][i] + c["assets"][i] for i in range(3)]
    out = {"object_score": (f1(*c["entities"]) + f1(*obj)) / 2}
    for k in KINDS:
        tp, fp, fn = c[k]
        out[f"{k}_precision"] = tp / (tp + fp) if tp + fp else None
        out[f"{k}_recall"] = tp / (tp + fn) if tp + fn else None
        out[f"{k}_f1"] = f1(tp, fp, fn)
    return out


def main() -> None:
    gt: dict = {}
    data = {s: rows_for(s) for s in GROUPS}
    for rows in data.values():
        for (clip, _), r in rows.items():
            gt[clip] = {k: len(r["ground_truth"][k]) for k in KINDS}
    planned = [(c, rep) for c in sorted(gt) for rep in (1, 2)]
    out = []
    for s, rows in data.items():
        valid = [r for r in rows.values() if r["outcome"] == "scored"]
        invalid = [gt[k[0]] for k, r in rows.items() if r["outcome"] in ("contract_invalid", "parse_failure")]
        other = [gt[k[0]] for k in planned if k not in rows or rows[k]["outcome"] not in MO]
        for view, extra in (("valid_only", []), ("mixed_chart", invalid), ("end_to_end", invalid + other)):
            b = score(valid, extra)
            out.append({"subject": s, "view": view, "valid_runs": len(valid), "invalid_as_empty": len(invalid) if view != "valid_only" else 0,
                        "other_as_empty": len(other) if view == "end_to_end" else 0, **{k: round(v, 4) if v is not None else "" for k, v in b.items()}})
    with open(sys.argv[1], "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(r["subject"][:8], r["view"], r["valid_runs"], r["object_score"], "ent", r["entities_f1"], "inst", r["instruments_f1"], "asset", r["assets_f1"], "P/R ent", r["entities_precision"], r["entities_recall"])


if __name__ == "__main__":
    main()
