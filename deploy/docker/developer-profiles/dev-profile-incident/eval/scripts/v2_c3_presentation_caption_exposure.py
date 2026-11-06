# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Exploratory, unadjusted: contingency Track B raw P1 minus Track A Nano direct, split by whether captions reached P1.

    uv run --frozen python scripts/v2_c3_presentation_caption_exposure.py OUT.csv

DERIVED and not pre-registered as a contingency analysis: the contingency profile is not Track B, and clips with
captions are longer, so subsets are not exchangeable. Reads score files and stored responses only.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evalv2 import cluster_bootstrap as cb  # noqa: E402

R = Path("/home/hengz/evalv2-data/v2/runs")
TAIL = "scoring/evalv2-score-stage-v3/primary/%s-videos.jsonl"
A_RUNS = ("c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a")
B_RUN = "c3-track-b-contingency-nano-grounding"
MODEL_OUTPUT = ("scored", "contract_invalid", "parse_failure")


def rows(run: str) -> list:
    p = R / run / (TAIL % "live")
    if not p.exists():
        p = R / run / (TAIL % "offline")
    return [json.loads(x) for x in p.read_text().splitlines()]


def main() -> int:
    best: dict = {}
    for run in A_RUNS:
        for r in rows(run):
            if r["subject"] != "nano-direct":
                continue
            k = (r["incident_id"], r["repeat"])
            if k not in best or best[k]["outcome"] not in MODEL_OUTPUT:
                best[k] = r
    ctx = {}
    for line in (R / B_RUN / "attempts.jsonl").read_text().splitlines():
        a = json.loads(line)
        if a["outcome"] == "answered":
            h = a["response_ref"].split(":")[1]
            body = json.loads((R / B_RUN / "store/objects/vss-response" / h[:2] / f"{h}.json").read_text())["payload"]["body"]
            ctx[a["item_id"]] = bool((body["experiment"].get("caption") or {}).get("context_sent"))
    p1 = [r for r in rows(B_RUN) if r.get("stage", "p1") == "p1"]
    out = []
    for name, keep in (("all", lambda c: True), ("captions_sent", lambda c: ctx.get(c) is True),
                       ("no_captions", lambda c: ctx.get(c) is False)):
        b = [r for r in p1 if keep(r["incident_id"])]
        for rep in (1, 2):
            a = [dict(r, repeat=1) for k, r in best.items() if k[1] == rep and keep(k[0])]
            x = cb.paired_difference(b, a)
            for metric, v in x["metrics"].items():
                out.append({"subset": name, "direct_repeat": rep, "clips": x["clips"], "both_valid": x["both_valid_runs"],
                            "metric": metric, "pipeline_p1": v["a"], "direct": v["b"], "difference": v["difference"],
                            "ci_low": v["ci95"][0], "ci_high": v["ci95"][1], "excludes_zero": v["excludes_zero"],
                            "status": "DERIVED exploratory contingency; unadjusted"})
    with open(sys.argv[1], "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(sum(ctx.values()), len(ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
