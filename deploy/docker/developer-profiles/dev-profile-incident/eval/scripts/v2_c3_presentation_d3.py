# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""D3 chart data: C3-E evaluation-half and development results (offline).

    python3 scripts/v2_c3_presentation_d3.py OUT_CSV

Evaluation-half values come from results/c3e-test-v1.json; development values are the published figures in
methodology/c3e-dev-results-v1.md, read from results/c3e-dev-c1b-v1.json. All are AI-referenced.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

O = Path("/home/hengz/evalv2-data/v2/references/c3e-v1")
TEST, DEV = "results/c3e-test-v1.json", "results/c3e-dev-c1b-v1.json"
STATUS = "final, AI-referenced (not human-verified)"


def frac(m: dict) -> str:
    return f"{m['k']}/{m['n']} = {m['value']:.3f}" if m["n"] else "no scorable entries"


def ci(m: dict) -> str:
    return f"95% CI [{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}]" if m.get("ci95") else "counts only"


def block_rows(cells: dict, subject: str, label: str, n: str, source: str, status: str) -> list:
    c = cells["combined"]["all"]
    rows = []

    def add(metric: str, value: str, interval: str = "") -> None:
        rows.append({"metric": metric, "value": value, "subject": label, "dataset_n": n, "ci": interval,
                     "status": status, "source": f"{source}:{subject}"})

    add("Correct evidence, conditional on a scorable reference (IoU 0.5)", frac(c["correct_evidence_conditional"]),
        ci(c["correct_evidence_conditional"]))
    add("Correct evidence over all matched entries", frac(c["correct_evidence_over_all_matched"]))
    add("IoU >= 0.5 given a box reference", frac(c["iou_ge_0_5_given_box_reference"]))
    add("Median IoU with AI reference", f"{c['iou_median']:.3f}" if c["iou_median"] else "n/a")
    add("Temporal alignment", frac(c["temporal_alignment_conditional"]), ci(c["temporal_alignment_conditional"]))
    for tier, name in (("consensus_only", "consensus-only"), ("adjudicated_only", "adjudicated-only")):
        m = cells[tier]["all"]["correct_evidence_conditional"]
        add(f"Correct evidence, {name} references", frac(m), ci(m))
    return rows


def main() -> None:
    rows = []
    test = json.loads((O / TEST).read_text())
    for run in test["runs"]:
        cells = run["by_threshold"]["0.5"]["cells"]
        for subject, block in cells.items():
            cont = "nanoground" in subject
            label = "VSS Nano contingency (A5-B)" if cont else "Super pipeline, original C3 (2 runs only)"
            n = "evaluation half, 55 clips, 50 scored runs" if cont else "evaluation half, 2 scored runs of 55"
            status = STATUS + (", contingency" if cont else ", incomplete")
            rows += block_rows(block, subject, label, n, TEST, status)
            for t in ("0.3", "0.7"):
                m = run["by_threshold"][t]["cells"][subject]["combined"]["all"]["correct_evidence_conditional"]
                rows.append({"metric": f"Correct evidence, IoU {t} sensitivity", "value": frac(m), "subject": label,
                             "dataset_n": n, "ci": ci(m), "status": status, "source": f"{TEST}:{subject}"})
    dev = json.loads((O / DEV).read_text())
    cells = dev["by_threshold"]["0.5"]["cells"]
    for subject, block in cells.items():
        rows += block_rows(block, subject, f"{subject}, historical, Super grounding", "development, 25 clips", DEV,
                           "development, AI-referenced")
    p = dev["by_threshold"]["0.5"]["paired_nano_minus_super"]["combined"]
    rows.append({"metric": "Paired Nano - Super correct evidence", "value": f"{p['diff']:+.2f}", "difference": f"{p['diff']:+.2f}",
                 "subject": "Nano vs Super pipelines", "dataset_n": f"development, {p['clips']} clips, {p['entries'][0]} entries each",
                 "ci": f"95% CI [{p['ci95'][0]:.2f}, {p['ci95'][1]:.2f}]; p={p['p_two_sided']:.2f}", "status": "development, AI-referenced",
                 "source": DEV})
    cols = ["metric", "baseline", "value", "subject", "dataset_n", "difference", "ci", "status", "source"]
    with open(sys.argv[1], "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(len(rows))


if __name__ == "__main__":
    main()
