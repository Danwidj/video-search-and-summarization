# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Correction v1 (offline): final-stage object rows with failed runs kept; original and corrected side by side.

    python3 scripts/v2_corrections_v1.py OUT.csv

Frozen score files are read, never written. A run with an invalid output has no final row; it is an empty report here,
so its GT items are misses. Runs with no model output stay excluded, as in the C3 view.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

R = Path("/home/hengz/evalv2-data/v2/runs")
TAIL = "scoring/evalv2-score-stage-v3/primary/{}-videos.jsonl"
KINDS = ("entities", "instruments", "assets")
INVALID = ("contract_invalid", "parse_failure")


def f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def block(rows: list, extra: list) -> dict:
    c = {k: [0, 0, 0] for k in KINDS}
    for r in rows:
        for k in KINDS:
            x = r[k]["counts"]
            c[k][0] += x["tp"]
            c[k][1] += x["fp"]
            c[k][2] += x["fn"]
    for r in extra:
        for k in KINDS:
            c[k][2] += len(r["ground_truth"][k])
    obj = [c["instruments"][i] + c["assets"][i] for i in range(3)]
    e = c["entities"]
    return {"entity_recall": e[0] / (e[0] + e[2]), "entity_f1": f1(*e), "instrument_f1": f1(*c["instruments"]),
            "asset_f1": f1(*c["assets"]), "object_score": (f1(*e) + f1(*obj)) / 2}


def main() -> None:
    out = []
    for run, subject in (("c3-track-b-contingency-nano-grounding", "nano-pipeline-nanoground"), ("c1b", "nano-pipeline"),
                         ("c1b", "super-pipeline")):
        path = R / run / TAIL.format("live")
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows = [r for r in rows if r["subject"] == subject]
        final = [r for r in rows if r["stage"] == "final" and r["outcome"] == "scored"]
        done = {(r["incident_id"], r["repeat"]) for r in final}
        gone = [r for r in rows if r["stage"] == "p1" and r["outcome"] in INVALID and (r["incident_id"], r["repeat"]) not in done]
        a, b = block(final, []), block(final, gone)
        for k in a:
            out.append({"correction": "D2 final rows keep failed runs", "subject": subject, "run": run, "metric": k,
                        "original": round(a[k], 4), "corrected": round(b[k], 4), "failed_runs_added": len(gone)})
    with open(sys.argv[1], "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(r["subject"], r["metric"], r["original"], r["corrected"], r["failed_runs_added"])


if __name__ == "__main__":
    main()
