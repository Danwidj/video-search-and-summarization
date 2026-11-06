# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Presentation chart data for chat, dashboard and efficiency (offline, read-only on run directories).

    python3 scripts/v2_c3_presentation_tables.py OUT_DIR   (efficiency_raw.json must already be in OUT_DIR)

Writes d4_chat.csv, d5_dashboard.csv and d6_efficiency.csv. Every row carries its provenance and source key. No
metric is computed here beyond a ratio of stored counts; those columns are named as derived.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

R = Path("/home/hengz/evalv2-data/v2/runs")
CHAT = (("c3-chat-a5-oracle-judge", "oracle", "A5-c1 oracle corpus (frozen GT reports); references AI-generated"),
        ("c3-chat-a5-system-contingency-judge", "system",
         "A5-c2 CONTINGENCY corpus (Nano-grounded pipeline reports), not the original Super corpus"))


def metric(rows, base, name, m):
    if m is None:
        return
    rows.append({**base, "metric": name, "value": m.get("value"), "n": m.get("n"),
                 "ci_low": (m.get("ci95") or [None, None])[0], "ci_high": (m.get("ci95") or [None, None])[1]})


def chat(out: Path) -> None:
    rows = []
    for run, corpus, label in CHAT:
        src = f"{run}/score-judged/report.json"
        c = json.loads((R / src).read_text())["corpora"][corpus]
        for tier, t in c["tiers"].items():
            b = {"corpus": corpus, "provenance": label, "tier": tier, "answered": t["answered"],
                 "planned": c["coverage"]["planned"], "no_report": c["coverage"].get("no_report", 0), "source": src}
            a, ci, by_k = t["answers"], t["citations"], t["retrieval"].get("by_k", {})
            metric(rows, b, "exact_answer_accuracy", a["exact"])
            metric(rows, b, "refusal_recall", a["refusal"]["recall"])
            metric(rows, b, "false_refusal_rate", a["refusal"]["false_refusal_rate"])
            for k in ("contradiction_rate", "unsupported_claim_rate", "fact_recall"):
                metric(rows, b, f"judged_{k}", a["judged"][k])
            metric(rows, b, "citation_precision", ci["precision"])
            metric(rows, b, "citation_recall", ci["recall"])
            metric(rows, b, "citation_validity", ci["validity"])
            for k in ("recall", "coverage", "mrr"):
                metric(rows, b, f"retrieval_{k}_at_5", (by_k.get("@5") or {}).get(k))
        cost = c["cost"]
        rows.append({"corpus": corpus, "provenance": label, "tier": "all", "metric": "latency_ms_median",
                     "value": cost["latency_ms_median"], "n": cost["calls"], "source": src})
        rows.append({"corpus": corpus, "provenance": label, "tier": "all", "metric": "total_tokens",
                     "value": cost["total_tokens"], "n": cost["calls"], "source": src})
    write(out / "d4_chat.csv", rows)


def dashboard(out: Path) -> None:
    src = "c3-dashboard/scoring/evalv2-dashboard-score-v1/primary/dashboard-summary.json"
    s = json.loads((R / src).read_text())["subjects"]["ultra-chart"]
    base = {"subject": "ultra-chart", "provenance": "original C3", "tier": "ai_proposed", "source": src}
    rows = []
    for k, m in s["metrics"].items():
        if isinstance(m, dict) and "value" in m:
            iv = m.get("interval") or [None, None]
            rows.append({**base, "metric": k, "value": m["value"], "numerator": m.get("numerator"),
                         "denominator": m.get("denominator"), "ci_low": iv[0], "ci_high": iv[1]})
    for k, v in s["errors"].items():
        if not isinstance(v, dict):
            rows.append({**base, "metric": f"errors_{k}", "value": v, "denominator": s["items"]})
    write(out / "d5_dashboard.csv", rows)


def stage_tokens(run: Path) -> dict:
    per: dict = {}
    for line in (run / "attempts.jsonl").read_text().splitlines():
        a = json.loads(line)
        if a["outcome"] != "answered":
            continue
        for stage, v in (a.get("tokens") or {}).items():
            if isinstance(v, dict) and v.get("tokens") is not None:
                d = per.setdefault((a["subject"], stage), {"tokens": [], "calls": []})
                d["tokens"].append(v["tokens"])
                d["calls"].append(v.get("attempts") or 0)
    return per


def efficiency(out: Path) -> None:
    raw = json.loads((out / "efficiency_raw.json").read_text())
    rows = []
    for group, d in raw.items():
        for subject, v in d["subjects"].items():
            final = v["final_rows_by_outcome"]
            valid = final.get("scored", final.get("ok", 0))
            att = v["attempts"]
            infra = sum(att.get(k, 0) for k in ("timeout", "rate_limited", "budget_exceeded", "http_error",
                                                "request_failed"))
            rows.append({"group": group, "subject": subject, "models": ";".join(v["models"]),
                         "attempts_total": v["attempts_total"],
                         "attempts_success": att.get("ok", 0) + att.get("answered", 0),
                         "attempts_timeout": att.get("timeout", 0), "attempts_rate_limited": att.get("rate_limited", 0),
                         "attempts_budget_exceeded": att.get("budget_exceeded", 0),
                         "attempts_http_or_request_failed": att.get("http_error", 0) + att.get("request_failed", 0),
                         "attempts_contract_rejected": att.get("contract_rejected", 0),
                         "infrastructure_failed_attempts": infra, "items_with_checkpoint_row":
                         v["items_with_a_checkpoint_row"], "valid_outputs": valid,
                         "derived_attempts_per_valid_output": round(v["attempts_total"] / valid, 3) if valid else None,
                         "tokens_median_answered": v["tokens_per_answered_attempt_median"],
                         "tokens_total_answered": v["tokens_answered_total"],
                         "latency_s_p50_answered": v["latency_s_answered"]["p50"],
                         "latency_s_p95_answered": v["latency_s_answered"]["p95"],
                         "latency_s_p50_all": v["latency_s_all_attempts"]["p50"],
                         "latency_s_p95_all": v["latency_s_all_attempts"]["p95"],
                         "measured_cost_usd": v["measured_cost_usd"] if v["calls_with_cost"] else None,
                         "derived_cost_per_valid_output_usd":
                         round(v["measured_cost_usd"] / valid, 6) if valid and v["calls_with_cost"] else None,
                         "source": f"efficiency_raw.json:{group}.subjects.{subject}"})
    write(out / "d6_efficiency.csv", rows)
    stages = []
    for name in ("c3-track-b-contingency-nano-grounding", "c3-track-b-historical"):
        for (subject, stage), v in sorted(stage_tokens(R / name).items()):
            t = sorted(v["tokens"])
            stages.append({"run": name, "subject": subject, "stage": stage, "answered_items": len(t),
                           "tokens_median": t[len(t) // 2], "tokens_total": sum(t),
                           "calls_total": sum(v["calls"])})
    write(out / "d6_pipeline_stage_tokens.csv", stages)


def write(path: Path, rows: list) -> None:
    cols: list = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(path.name, len(rows))


if __name__ == "__main__":
    o = Path(sys.argv[1])
    chat(o)
    dashboard(o)
    efficiency(o)
