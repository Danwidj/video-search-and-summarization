# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 model efficiency (offline, read-only on run directories): every attempt counts, failures included.

    uv run --frozen python scripts/v2_c3_efficiency.py OUT.json GROUP=RUN_DIR[,RUN_DIR...] [GROUP=...]

Per group and subject: attempts by outcome; final items by outcome (last checkpoint row per item); attempts per
final item; tokens per answered attempt (Track A: total; Track B and chat: summed over stages/kinds); latency p50/p95
over all attempts and over answered ones (a timeout counts at its waited time); measured cost from each stored
response's ``usage.cost`` (OpenRouter; Switchyard calls are a free quota and record no cost). Groups keep original C3,
recovery, contingency and historical runs apart.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SUCCESS = ("ok", "answered")  # Track A / dashboard report "ok"; Track B reports "answered"


def pct(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)


def tokens(row):
    t = row.get("tokens") or {}
    if "total" in t:
        return t.get("total")
    vals = [x.get("tokens") for x in t.values() if isinstance(x, dict) and x.get("tokens") is not None]
    return sum(vals) if vals else None


def response_cost(run: Path, ref: str | None):
    if not ref or not ref.startswith("response:"):
        return None
    digest = ref.split(":", 1)[1]
    path = run / "store" / "objects" / "response" / digest[:2] / f"{digest}.json"
    if not path.exists():
        return None
    body = json.loads(path.read_text())
    body = body.get("payload", body)
    return ((body or {}).get("usage") or {}).get("cost")


def group_stats(runs):
    per = defaultdict(lambda: {"attempts": Counter(), "final": Counter(), "lat_all": [], "lat_ok": [], "tok": [],
                               "cost": 0.0, "cost_calls": 0, "items": set(), "models": set()})
    last = {}  # across the group, in run order: a later run's row supersedes an earlier run's for the same item
    for run in runs:
        run = Path(run)
        for line in (run / "attempts.jsonl").read_text().splitlines() if (run / "attempts.jsonl").exists() else []:
            a = json.loads(line)
            s = per[a["subject"]]
            s["attempts"][a["outcome"]] += 1
            s["models"].add(a.get("model"))
            if a.get("latency_ms") is not None:
                s["lat_all"].append(a["latency_ms"] / 1000)
                if a["outcome"] in SUCCESS:
                    s["lat_ok"].append(a["latency_ms"] / 1000)
            if a["outcome"] in SUCCESS and tokens(a) is not None:
                s["tok"].append(tokens(a))
            c = response_cost(run, a.get("response_ref"))
            if c is not None:
                s["cost"] += float(c)
                s["cost_calls"] += 1
        cp = run / "checkpoint.jsonl"
        for line in cp.read_text().splitlines() if cp.exists() else []:
            r = json.loads(line)
            last[(r.get("subject"), r.get("item_id"), r.get("repeat"))] = r
    for (subject, item, rep), r in last.items():
        per[subject]["final"][r["outcome"]] += 1
        per[subject]["items"].add((item, rep))
    out = {}
    for subject, s in sorted(per.items()):
        n_att = sum(s["attempts"].values())
        out[subject] = {"models": sorted(m for m in s["models"] if m), "attempts": dict(s["attempts"]),
                        "attempts_total": n_att, "items_with_a_checkpoint_row": len(s["items"]),
                        "final_rows_by_outcome": dict(s["final"]),
                        "attempts_per_item": round(n_att / len(s["items"]), 3) if s["items"] else None,
                        "tokens_per_answered_attempt_median": pct(s["tok"], 0.5),
                        "tokens_answered_total": sum(s["tok"]),
                        "latency_s_all_attempts": {"p50": pct(s["lat_all"], 0.5), "p95": pct(s["lat_all"], 0.95),
                                                   "n": len(s["lat_all"])},
                        "latency_s_answered": {"p50": pct(s["lat_ok"], 0.5), "p95": pct(s["lat_ok"], 0.95),
                                               "n": len(s["lat_ok"])},
                        "measured_cost_usd": round(s["cost"], 6), "calls_with_cost": s["cost_calls"]}
    return out


def main() -> int:
    out = Path(sys.argv[1])
    groups = {}
    for spec in sys.argv[2:]:
        name, _, runs = spec.partition("=")
        groups[name] = {"runs": runs.split(","), "subjects": group_stats(runs.split(","))}
    out.write_text(json.dumps(groups, indent=1, sort_keys=True) + "\n")
    print(json.dumps({g: {s: (v["attempts_total"], v["latency_s_answered"]["p50"], v["measured_cost_usd"])
                          for s, v in d["subjects"].items()} for g, d in groups.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
