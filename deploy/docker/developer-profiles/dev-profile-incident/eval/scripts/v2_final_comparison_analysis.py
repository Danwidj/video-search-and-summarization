# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Final VLM versus VSS comparison, frozen analysis (methodology/v2-final-comparison-plan-v1.md). Offline, read-only.

    uv run --frozen python scripts/v2_final_comparison_analysis.py OUT.json --vss RUN [--vss-stage final]
        --direct RUN [--direct RUN ...] [--direct-subject nano-direct] [--repeats 2]

Rows come from each run's judged score file when present, else its offline file. A direct item takes the first row
holding a model output, as in the C3 analysis. Failed or missing items are never dropped from the end-to-end view.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path


TAIL = "scoring/evalv2-score-stage-v3/primary/{}-videos.jsonl"
MODEL_OUTPUT = ("scored", "contract_invalid", "parse_failure")
KINDS = ("entities", "instruments", "assets")
SEED, N = 20261027, 10000


def run_rows(run: Path) -> list:
    path = run / TAIL.format("live")
    if not path.exists():
        path = run / TAIL.format("offline")
    return [json.loads(x) for x in path.read_text().splitlines()]


def f1(tp: float, fp: float, fn: float) -> float:
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def sev_error(row: dict) -> float | None:
    s = row["incident_field_scores"].get("severity_level") or {}
    return None if s.get("expected") is None or s.get("predicted") is None else abs(float(s["predicted"]) - float(s["expected"]))


def type_ok(row: dict | None) -> float:
    return 1.0 if row and row["outcome"] == "scored" and (row["incident_field_scores"].get("type") or {}).get("pass") else 0.0


def counts(row: dict | None, ref: dict) -> dict:
    """A kind's (tp, fp, fn); a failed item is an empty report, so every reference item is a miss."""
    if row and row["outcome"] == "scored":
        return {k: (row[k]["counts"]["tp"], row[k]["counts"]["fp"], row[k]["counts"]["fn"]) for k in KINDS}
    return {k: (0, 0, ref[k]) for k in KINDS}


def pooled(items: list) -> dict:
    tot = {k: [0, 0, 0] for k in KINDS}
    for c in items:
        for k in KINDS:
            for i in range(3):
                tot[k][i] += c[k][i]
    obj = [tot["instruments"][i] + tot["assets"][i] for i in range(3)]
    return {"entity_f1": f1(*tot["entities"]), "instrument_f1": f1(*tot["instruments"]), "asset_f1": f1(*tot["assets"]),
            "object_score": (f1(*tot["entities"]) + f1(*obj)) / 2}


def mean(xs: list) -> float | None:
    return sum(xs) / len(xs) if xs else None


def boot(keys: list, stat) -> dict:
    """A - B point value, clip-cluster percentile CI and two-sided p; ``stat(keys)`` returns (a, b)."""
    clips = sorted({k[0] for k in keys})
    by = {c: [k for k in keys if k[0] == c] for c in clips}
    a, b = stat(keys)
    if a is None or b is None:
        return {"a": a, "b": b, "diff": None, "pairs": len(keys), "clips": len(clips)}
    rnd = random.Random(SEED)
    sample = []
    for _ in range(N):
        ks = [k for _ in clips for k in by[clips[rnd.randrange(len(clips))]]]
        x, y = stat(ks)
        if x is not None and y is not None:
            sample.append(x - y)
    sample.sort()
    p = min(1.0, 2 * min(sum(s <= 0 for s in sample), sum(s >= 0 for s in sample)) / len(sample))
    return {"a": round(a, 4), "b": round(b, 4), "diff": round(a - b, 4), "pairs": len(keys), "clips": len(clips),
            "ci95": [round(sample[int(.025 * len(sample))], 4), round(sample[int(.975 * len(sample)) - 1], 4)], "p": round(p, 4)}


def holm(ps: list) -> list:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = round(run, 4)
    return adj


def field_mae(row: dict, key: str) -> float | None:
    s = row["incident_field_scores"].get(key) or {}
    if s.get("expected") is None or s.get("predicted") is None:
        return None
    return abs(float(s["predicted"]) - float(s["expected"]))


def judged_pass(row: dict) -> float | None:
    d = row["incident_field_scores"].get("description") or {}
    return None if d.get("pass") is None else (1.0 if d["pass"] else 0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--vss", type=Path, required=True)
    ap.add_argument("--vss-stage", default="final")
    ap.add_argument("--direct", type=Path, action="append", required=True)
    ap.add_argument("--direct-subject", default="nano-direct")
    ap.add_argument("--repeats", type=int, default=2)
    a = ap.parse_args()
    direct: dict = {}
    for run in a.direct:
        for r in run_rows(run):
            if r["subject"] != a.direct_subject or r.get("stage", "p1") != "p1":
                continue
            k = (r["incident_id"], r["repeat"])
            if k not in direct or direct[k]["outcome"] not in MODEL_OUTPUT:
                direct[k] = r
    vss: dict = {}
    for r in run_rows(a.vss):
        if r.get("stage", "p1") == a.vss_stage:
            vss[(r["incident_id"], r["repeat"])] = r
    clips = sorted({k[0] for k in direct})
    planned = [(c, rep) for c in clips for rep in range(1, a.repeats + 1)]
    # Reference item counts come from the ground truth each score row carries, failed rows included.
    ref = {}
    for row in [*direct.values(), *vss.values()]:
        ref[row["incident_id"]] = {k: len(row["ground_truth"][k]) for k in KINDS}

    def e2e_type(ks):
        return mean([type_ok(vss.get(k)) for k in ks]), mean([type_ok(direct.get(k)) for k in ks])

    def e2e_obj(name):
        def stat(ks):
            return (pooled([counts(vss.get(k), ref[k[0]]) for k in ks])[name],
                    pooled([counts(direct.get(k), ref[k[0]]) for k in ks])[name])
        return stat

    valid = [k for k in planned if k in vss and k in direct and vss[k]["outcome"] == "scored" and direct[k]["outcome"] == "scored"]

    def on_valid(fn):
        def stat(ks):
            pairs = [(fn(vss[k]), fn(direct[k])) for k in ks]
            pairs = [p for p in pairs if p[0] is not None and p[1] is not None]
            return mean([p[0] for p in pairs]), mean([p[1] for p in pairs])
        return stat

    primary = {"type_accuracy_e2e": boot(planned, e2e_type), "object_score_e2e": boot(planned, e2e_obj("object_score")),
               "severity_mae_valid": boot(valid, on_valid(sev_error))}
    for name, h in zip(primary, holm([primary[m]["p"] for m in primary]), strict=True):
        primary[name]["p_holm"] = h
    secondary = {"type_accuracy_valid": boot(valid, on_valid(lambda r: type_ok(r))),
                 "object_score_valid": boot(valid, e2e_obj("object_score")),
                 "start_mae_s": boot(valid, on_valid(lambda r: field_mae(r, "start_timestamp"))),
                 "end_mae_s": boot(valid, on_valid(lambda r: field_mae(r, "end_timestamp"))),
                 "description_pass": boot(valid, on_valid(judged_pass)),
                 "entity_f1_e2e": boot(planned, e2e_obj("entity_f1")),
                 "instrument_f1_e2e": boot(planned, e2e_obj("instrument_f1")),
                 "asset_f1_e2e": boot(planned, e2e_obj("asset_f1"))}
    keys = [m for m in secondary if secondary[m].get("p") is not None]
    for name, h in zip(keys, holm([secondary[m]["p"] for m in keys]), strict=True):
        secondary[name]["p_holm"] = h
    out = {"plan": "v2-final-comparison-plan-v1", "planned_pairs": len(planned), "valid_pairs": len(valid),
           "vss_outcomes": dict(collections.Counter(vss[k]["outcome"] if k in vss else "missing" for k in planned)),
           "direct_outcomes": dict(collections.Counter(direct[k]["outcome"] if k in direct else "missing" for k in planned)),
           "primary": primary, "secondary": secondary}
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: {"diff": v.get("diff"), "ci95": v.get("ci95"), "p_holm": v.get("p_holm"), "pairs": v.get("pairs")} for k, v in primary.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
