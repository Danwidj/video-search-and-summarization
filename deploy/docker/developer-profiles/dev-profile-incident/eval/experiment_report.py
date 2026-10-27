# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Experiment reports, reproducibility checks, budget statements and the selection guard (PR 7).

Everything here reads saved results only: no model, judge or network call.

- ``render`` writes a Markdown report for named configurations (``C1``..``C4`` for Stage 3,
  any names for a stage report): configuration, incident fields with intervals, severity,
  items, reliability, **inference** latency and, apart from it, end-to-end latency, the four
  paired comparisons with the C3-C1 decomposition, and the plan's interpretation limits and
  held-out exposure disclosure. A report over any non-reportable record (candidate ground
  truth, a plumbing run) says so at the top and cannot be mistaken for a result.
- ``verify`` re-checks a saved run: the results hash, the prompt bytes against the registry,
  the config hash, the frozen ground truth's digest, the split and the planned call count.
- ``budget`` states the call volume per stage from the configs (tokens and cost stay unknown
  until the Stage 0 pilot measures them).
- ``select`` applies a **pre-registered** selection rule to **dev** results only; it refuses
  test-split records and refuses to run until the rule is recorded in ``.docs/decisions.md``
  (plan D9 is not decided by this code).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import experiment_runner as er
import extraction_stats
import prompt_registry

ITEM_KINDS = ("entities", "instruments", "assets")


# --- metrics from saved records -------------------------------------------------------------------

def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return round(ordered[index], 2)


def latency(record: dict) -> dict:
    """Inference latency (P1 only) and, separately, end-to-end latency, in seconds."""
    inference, end_to_end = [], []
    for video in record["videos"]:
        transport = video.get("transport") or {}
        if record["arm"] == "vss":
            if transport.get("p1_elapsed_ms") is not None:
                inference.append(transport["p1_elapsed_ms"] / 1000.0)
            if transport.get("end_to_end_s") is not None:
                end_to_end.append(transport["end_to_end_s"])
        elif (video.get("timing") or {}).get("p1_elapsed_s") is not None:
            inference.append(video["timing"]["p1_elapsed_s"])
    return {"inference": {"n": len(inference), "p50": _percentile(inference, 0.5), "p95": _percentile(inference, 0.95)},
            "end_to_end": {"n": len(end_to_end), "p50": _percentile(end_to_end, 0.5),
                           "p95": _percentile(end_to_end, 0.95)}}


def items(record: dict) -> dict:
    """Pooled precision, recall and F1 per item kind over videos with a model output."""
    out = {}
    for kind in ITEM_KINDS:
        tp = fp = fn = 0
        for video in record["videos"]:
            if not extraction_stats.has_model_output(video):
                continue
            summary = video.get(kind) or {}
            tp += len(summary.get("matches", []))
            fp += len(summary.get("unmatched_model", []))
            fn += len(summary.get("unmatched_gt", []))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
        out[kind] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
    return out


def _fmt(value, digits: int = 3) -> str:
    return "–" if value is None else (f"{value:.{digits}f}" if isinstance(value, float) else str(value))


def _ci(interval) -> str:
    return "–" if not interval else f"[{interval[0]:.3f}, {interval[1]:.3f}]"


# --- the report ----------------------------------------------------------------------------------

LIMITS = [
    "Pipeline effect (C2−C1, C3−C4) is VSS minus direct VLM at the same prompt. Today's VSS adds nothing before "
    "extraction, so a non-zero value is a pipeline or reliability difference (transport, retries, failure handling, "
    "upstream non-determinism), never an architectural extraction advantage (plan §F.1).",
    "Prompt-engineering effect (C3−C2, C4−C1) is the optimised prompt minus the baseline within one arm.",
    "C3−C1 is reported only as the sum (C3−C4) + (C4−C1).",
    "Inference latency (P1 only) and end-to-end latency are separate measurements and are never compared with each "
    "other.",
]
EXPOSURE = [
    "The 55 test clips are not unseen (plan §F.5): they were in the 2026-10-02 benchmark, and three of them shaped "
    "earlier prompt pilots. Any bias favours the baseline prompt, so prompt gains are conservative; absolute "
    "accuracy levels may be optimistic and are not comparable with the 2026-10-02 figures.",
]


def render(records: dict[str, dict], *, title: str) -> str:
    reportable = all(r.get("reportable") for r in records.values())
    pilot = any(r.get("purpose") == "pilot" for r in records.values())
    lines = [f"# {title}", ""]
    if pilot:
        lines += ["> **PILOT: infrastructure, reliability, latency and cost only.** Accuracy is deliberately not "
                  "shown: pilot results are never used for prompt selection or reported as accuracy.", ""]
    elif not reportable:
        lines += ["> **NOT REPORTABLE.** At least one configuration ran on candidate (unfrozen) ground truth or is a "
                  "plumbing run. These numbers test the machinery only and must not be cited.", ""]
    lines += ["## Configurations", "", "| Name | Experiment | Arm | Model | Prompt (sha256) | Split | Repeats | Ground truth "
              "| Videos | Harness |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in records.items():
        lines.append(f"| {name} | `{r['experiment_id']}` | {r['arm']} | `{r['model']}` | `{r['prompt']['id']}` "
                     f"(`{r['prompt']['sha256'][:12]}`) | {r['split']['half']} | {r['plan']['repeats']} | "
                     f"{r['ground_truth']['version']} ({r['ground_truth']['status']}) | {r['plan']['videos']} | "
                     f"`{str(r['harness_git_sha'])[:9]}` |")
    stopped = {n: r.get("stopped") for n, r in records.items() if r.get("stopped") or not r.get("complete", True)}
    if stopped:
        lines += ["", f"> **Incomplete:** {stopped}"]
    lines += ["", "## Usage and gateway cost", "", "| Name | P1 calls | P1 tokens | Tokens per call | Judge calls | Judge "
              "tokens | Gateway cost (USD) |", "|---|---|---|---|---|---|---|"]
    for name, r in records.items():
        u = usage(r)
        judge = u["judge_tokens"] if u["judge_tokens"] else f"{u['judge_tokens_estimate']} (est.)"
        lines.append(f"| {name} | {u['p1_calls']} | {u['p1_tokens']} | {_fmt(u['tokens_per_p1_call'], 0)} | "
                     f"{u['judge_calls']} | {judge} | {_fmt(u['cost_usd_provisional'], 4)} |")
    if pilot:
        return "\n".join(lines + _pilot_sections(records))
    lines += ["", "## Incident fields", "", "Conditional accuracy (videos with a model output and a scored value) with "
              "its 95% interval, then end-to-end accuracy (a request failure counts as a miss).", "",
              "| Name | Field | n | Accuracy | 95% CI | End-to-end n | End-to-end | 95% CI |",
              "|---|---|---|---|---|---|---|---|"]
    for name, r in records.items():
        for field, stats in extraction_stats.field_intervals(r["videos"]).items():
            e2e = stats["end_to_end"]
            lines.append(f"| {name} | {field} | {stats['n']} | {_fmt(stats['accuracy'])} | {_ci(stats['ci95'])} | "
                         f"{e2e['n']} | {_fmt(e2e['accuracy'])} | {_ci(e2e['ci95'])} |")
    lines += ["", "## Severity", "", "| Name | n | Exact | Within one | Mean signed error |", "|---|---|---|---|---|"]
    for name, r in records.items():
        sev = extraction_stats.severity_analysis(r["videos"])
        lines.append(f"| {name} | {sev['n']} | {_fmt(sev['exact'])} | {_fmt(sev['within_one'])} | "
                     f"{_fmt(sev['mean_signed_error'])} |")
    lines += ["", "## Entities, instruments and assets (pooled)", "", "| Name | Kind | TP | FP | FN | Precision | Recall "
              "| F1 |", "|---|---|---|---|---|---|---|---|"]
    for name, r in records.items():
        for kind, s in items(r).items():
            lines.append(f"| {name} | {kind} | {s['tp']} | {s['fp']} | {s['fn']} | {_fmt(s['precision'])} | "
                         f"{_fmt(s['recall'])} | {_fmt(s['f1'])} |")
    lines += ["", "## Reliability", "", "| Name | Attempted | Outcomes | Model-output rate | Valid-output rate |",
              "|---|---|---|---|---|"]
    for name, r in records.items():
        rel = extraction_stats.reliability(r["videos"])
        lines.append(f"| {name} | {rel['attempted']} | {rel['outcomes']} | {_fmt(rel['model_output_rate'])} | "
                     f"{_fmt(rel['valid_output_rate'])} |")
    lines += ["", "## Inference latency (P1 only, seconds)", "", "| Name | n | p50 | p95 |", "|---|---|---|---|"]
    lat = {name: latency(r) for name, r in records.items()}
    for name, value in lat.items():
        i = value["inference"]
        lines.append(f"| {name} | {i['n']} | {_fmt(i['p50'], 2)} | {_fmt(i['p95'], 2)} |")
    if any(v["end_to_end"]["n"] for v in lat.values()):
        lines += ["", "## End-to-end latency (VSS `/analyze`, seconds; not comparable with inference latency)", "",
                  "| Name | n | p50 | p95 |", "|---|---|---|---|"]
        for name, value in lat.items():
            e = value["end_to_end"]
            if e["n"]:
                lines.append(f"| {name} | {e['n']} | {_fmt(e['p50'], 2)} | {_fmt(e['p95'], 2)} |")
    if {"C1", "C2", "C3", "C4"} & set(records):
        table = er.four_way(records)
        lines += ["", "## Paired comparisons (mean B − A per video, repeats averaged, 95% bootstrap CI)", ""]
        lines += [f"- Configuration problems: {'; '.join(table['problems'])}" if table["problems"]
                  else "- C1–C4 share model, ground truth, split, methodology and video set."]
        lines += ["", "| Comparison | Meaning | Field | Pairs | Mean difference | 95% CI |", "|---|---|---|---|---|---|"]
        for comparison, block in table["comparisons"].items():
            for field, diff in block["fields"].items():
                lines.append(f"| {comparison} | {block['meaning']} | {field} | {diff['n_pairs']} | "
                             f"{_fmt(diff['mean_difference'])} | {_ci(diff['ci95'])} |")
    lines += ["", "## Interpretation limits", ""] + [f"- {item}" for item in LIMITS]
    lines += ["", "## Held-out exposure", ""] + [f"- {item}" for item in EXPOSURE] + [""]
    return "\n".join(lines)


def usage(record: dict) -> dict:
    calls = len(record["videos"])
    tokens = sum(((v.get("usage") or {}).get("p1_total_tokens") or 0) for v in record["videos"])
    return {"p1_calls": calls, "p1_tokens": tokens, "tokens_per_p1_call": tokens / calls if calls else None,
            "judge_calls": sum(((v.get("usage") or {}).get("judge_calls") or 0) for v in record["videos"]),
            "judge_tokens": sum(((v.get("usage") or {}).get("judge_tokens") or 0) for v in record["videos"]),
            "judge_tokens_estimate": sum(((v.get("usage") or {}).get("judge_tokens_estimate") or 0)
                                         for v in record["videos"]),
            "cost_usd_provisional": round(sum(((v.get("usage") or {}).get("cost_usd_provisional") or 0)
                                              for v in record["videos"]), 6)}


def _pilot_sections(records: dict[str, dict]) -> list[str]:
    lines = ["", "## Reliability", "", "| Name | Attempted | Outcomes | Model-output rate | Valid-output rate | "
             "Rate-limit retries |", "|---|---|---|---|---|---|"]
    for name, r in records.items():
        rel = extraction_stats.reliability(r["videos"])
        retries = sum(((v.get("p1_raw") or {}).get("rate_limit") or {}).get("rate_limit_retries", 0) for v in r["videos"])
        lines.append(f"| {name} | {rel['attempted']} | {rel['outcomes']} | {_fmt(rel['model_output_rate'])} | "
                     f"{_fmt(rel['valid_output_rate'])} | {retries} |")
    lines += ["", "## Latency (seconds)", "", "| Name | Inference n | p50 | p95 | End-to-end n | p50 | p95 |",
              "|---|---|---|---|---|---|---|"]
    for name, r in records.items():
        lat = latency(r)
        i, e = lat["inference"], lat["end_to_end"]
        lines.append(f"| {name} | {i['n']} | {_fmt(i['p50'], 2)} | {_fmt(i['p95'], 2)} | {e['n']} | "
                     f"{_fmt(e['p50'], 2)} | {_fmt(e['p95'], 2)} |")
    crops = {}
    for name, r in records.items():
        gaps = [e.get("image_gap") for v in r["videos"] for e in ((v.get("transport") or {}).get("evidence") or [])]
        if gaps:
            crops[name] = {"items": len(gaps), "with_gap": sum(1 for g in gaps if g)}
    if crops:
        lines += ["", f"Evidence crops (end-to-end pilot): {crops}"]
    return lines + [""]


def measure(records: list[dict]) -> dict:
    """Pilot measurements for ``budget(measured=...)``: tokens and judge calls per call, rate limiting, latency."""
    videos = [v for r in records for v in r["videos"]]
    tokens = [(v.get("usage") or {}).get("p1_total_tokens") or 0 for v in videos if (v.get("usage") or {})
              .get("p1_total_tokens")]
    attempts = sum(((v.get("p1_raw") or {}).get("rate_limit") or {}).get("attempt_count", 1) for v in videos)
    limited = sum(len(((v.get("p1_raw") or {}).get("rate_limit") or {}).get("rate_limit_rejections") or [])
                  for v in videos)
    return {"p1_calls": len(videos), "tokens_per_p1_call": sum(tokens) / len(tokens) if tokens else None,
            "tokens_per_p1_call_max": max(tokens) if tokens else None,
            "judge_calls_per_video": sum(v.get("judge_calls") or 0 for v in videos) / len(videos) if videos else None,
            "rate_limited_share": limited / attempts if attempts else None,
            "latency": {r["experiment_id"]: latency(r) for r in records}}


# --- reproducibility --------------------------------------------------------------------------------

def verify(results_dir: Path, *, registry: dict | None = None, split: dict | None = None,
           gt_manifest: dict | None = None) -> list[str]:
    """Problems with a saved run; empty when it reproduces its recorded identity."""
    problems = []
    content = (results_dir / "results.json").read_bytes()
    recorded = (results_dir / "results.sha256").read_text().split()[0] if (results_dir / "results.sha256").exists() \
        else None
    if recorded != hashlib.sha256(content).hexdigest():
        problems.append("results.json does not match results.sha256 (edited after the run, or no hash)")
    record = json.loads(content)
    prompt = (results_dir / "prompt.txt").read_bytes()
    if hashlib.sha256(prompt).hexdigest() != record["prompt"]["sha256"]:
        problems.append("prompt.txt is not the prompt the run recorded")
    try:
        if prompt_registry.entry(record["prompt"]["id"], registry)["sha256"] != record["prompt"]["sha256"]:
            problems.append("the registry's prompt differs from the one the run used")
    except prompt_registry.RegistryError as exc:
        problems.append(str(exc))
    if hashlib.sha256(json.dumps(record["config"], sort_keys=True).encode()).hexdigest() != record["config_sha256"]:
        problems.append("config_sha256 does not match the recorded config")
    if gt_manifest is not None and gt_manifest.get("records_sha256") != record["ground_truth"]["records_sha256"]:
        problems.append("the frozen ground truth differs from the one the run used")
    if split is not None:
        try:
            expected = sorted(er.videos_for(record["config"], split))
        except er.ExperimentRefused as exc:
            expected = None
            problems.append(str(exc))
        if expected is not None and sorted({v["incident_id"] for v in record["videos"]}) != expected:
            problems.append("the run's videos are not its configured split videos")
    if len(record["videos"]) != record["plan"]["planned_p1_calls"]:
        problems.append(f"{len(record['videos'])} video results for {record['plan']['planned_p1_calls']} planned calls")
    if not record.get("complete"):
        problems.append("the run did not complete")
    return problems


# --- budget -------------------------------------------------------------------------------------

JUDGE_CALLS_PER_SCORED_VIDEO = 5  # plan D11 estimate (incident plus matched-item descriptions); the pilot measures it


def budget(configs: list[dict], split: dict, *, pricing: dict | None = None, measured: dict | None = None) -> dict:
    """Requests, tokens and provisional cost per config: planning estimates, or the pilot's measurements.

    Caps (``budget`` in each config) are hard and enforced by the runner; the cost is provisional
    while ``pricing.provisional`` is true.
    """
    pricing = pricing or er.load_pricing()
    per_call = (measured or {}).get("tokens_per_p1_call") or er.P1_TOKENS_PLANNING_MEAN
    judge_per_video = (measured or {}).get("judge_calls_per_video") or JUDGE_CALLS_PER_SCORED_VIDEO
    rows = []
    for config in configs:
        p1 = er.planned_calls(config, split)
        judge = round(p1 * judge_per_video)
        p1_tokens = round(p1 * per_call)
        judge_tokens = judge * pricing["judge_tokens_per_call_estimate"]
        cost = p1_tokens / 1e6 * er._rate(pricing, config["model"]) + judge_tokens / 1e6 * er._rate(
            pricing, pricing["judge_model"])
        planning = pricing.get("planning_rate_usd_per_million_tokens")
        rows.append({"experiment_id": config["experiment_id"], "purpose": config["purpose"], "arm": config["arm"],
                     "p1_calls": p1, "judge_calls_estimate": judge, "p1_tokens_estimate": p1_tokens,
                     "judge_tokens_estimate": judge_tokens, "cost_usd_provisional": round(cost, 2),
                     # What the same volume would cost at the planning rate (never the gateway's charge).
                     "cost_usd_at_planning_rate": round((p1_tokens + judge_tokens) / 1e6 * planning, 2)
                     if planning is not None else None,
                     "crop_calls": 0 if config["pipeline"].get("skip_crops") else "unmeasured (≤ 4 per item)",
                     "caps": config["budget"]})
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in ("p1_calls", "judge_calls_estimate",
                                                                          "p1_tokens_estimate",
                                                                          "judge_tokens_estimate",
                                                                          "cost_usd_provisional")},
            "basis": "pilot measurements" if measured else "planning estimates (2026-10-02 aggregate usage)",
            "pricing_provisional": pricing.get("provisional", True), "pricing_source": pricing.get("source"),
            "infrastructure_cost": pricing.get("infrastructure_cost")}


# --- selection ----------------------------------------------------------------------------------

class SelectionRefused(RuntimeError):
    """Selection was asked to use test results, or the rule is not pre-registered."""


def select(candidates: dict[str, dict], baseline: dict, *, rule_record: str, rule, decisions_path: Path) -> dict:
    """Apply a pre-registered rule (``rule(candidate_record, baseline_record) -> score or None``) to dev results.

    Refuses any test-split or non-reportable record, and refuses unless ``rule_record`` is an
    existing ``### `` heading in decisions.md, so the rule is fixed before results are seen.
    """
    import experiment_selection

    try:
        experiment_selection.guard({**candidates, "baseline": baseline}, rule_record=rule_record,
                                   decisions_path=decisions_path)
    except experiment_selection.SelectionRefused as exc:
        raise SelectionRefused(str(exc)) from exc
    scores = {name: rule(record, baseline) for name, record in candidates.items()}
    eligible = {name: score for name, score in scores.items() if score is not None}
    winner = max(eligible, key=eligible.get) if eligible else None
    return {"rule_record": rule_record, "scores": scores, "selected": winner}
