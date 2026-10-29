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

"""Stage 3 (final held-out C1-C4 comparison): reproducibility manifest, offline preflight, budget and report.

Nothing here sends a request. The manifest pins every input that is not under test (configs, prompt
hashes, model and P1 settings, ground-truth digest, methodology, test clips, seeds, retry and recovery
policy, caps); the preflight recomputes it and refuses any drift. The report reads saved results only:
D9 v2 differences (never a selection on test), severity v1.3, per category, latency split into model
processing and pipeline overhead, failures and representative clips.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import contract
import experiment_recovery as rec
import experiment_report
import experiment_runner as er
import experiment_selection as es
import extraction_stats
import methodology
import prompt_registry
import severity_metrics

EVAL_DIR = Path(__file__).resolve().parent
CONFIG_DIR = EVAL_DIR / "experiments" / "configs"
MANIFEST_PATH = EVAL_DIR / "experiments" / "stage3" / "manifest.json"
GT_MANIFEST_PATH = EVAL_DIR / "ground_truth" / "freeze" / "ground-truth-v1.0-MANIFEST.json"
AGENT_DIR = EVAL_DIR.parents[4] / "services" / "agent"
AGENT_PYTHON = Path(os.environ.get("VSS_AGENT_PYTHON", Path.home() / ".cache" / "vss-agent-venv" / "bin" / "python"))

SELECTION_RECORD = "2026-10-29: Stage 2 selection (D9 v2): p1-v4-e01-severity"
CONFIGS = {"C1": "s3-c1-direct-base", "C2": "s3-c2-vss-base", "C3": "s3-c3-vss-v1", "C4": "s3-c4-direct-v1"}
ROLES = {"C1": ("direct-vlm", "base"), "C2": ("vss", "base"), "C3": ("vss", "selected"), "C4": ("direct-vlm", "selected")}
# Keys that may differ between C1-C4: the arm and the prompt under test, and what follows from them.
PER_CONFIG_KEYS = {"experiment_id", "arm", "prompt_id", "baseline_ref", "description"}
# The only body difference allowed between the arms at one prompt: the agent sends the API default explicitly.
TRANSPORT_KEYS = {"stream"}
PARITY_URL = "https://example.invalid/video.mp4"
MAX_RECOVERED_RUNS = rec.MAX_RECOVERED_RUNS
# Measured Stage 2 rates (dev, Cosmos 3 Super), used only for the expected-usage estimate; never a cap.
MEASURED = {"p1_tokens_per_call": {"p1-v4-base": 9071, "p1-v4-e01-severity": 9245},
            "judge_calls_per_judged_field": round(418 / (101 * 1710 / 150), 3), "judge_tokens_per_call": 379,
            "video_runs_per_hour": (50, 70), "extra_attempt_share": (0.05, 0.13)}


def selected_prompt(record: str = SELECTION_RECORD) -> str:
    return record.rsplit(": ", 1)[1]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_configs(directory: Path = CONFIG_DIR) -> dict[str, dict]:
    return {name: er.load_config(directory / f"{eid}.json") for name, eid in CONFIGS.items()}


# --- manifest -------------------------------------------------------------------------------------

def stage_caps(configs: dict[str, dict], split: dict, gt_index: dict | None = None) -> dict:
    """Scheduled runs and hard caps: the stage (retry-v2 included) and the worst-case recovery-v1 on top."""
    rows = {}
    for name, config in configs.items():
        planned = er.planned_calls(config, split)
        row = {"video_runs": planned, **config["budget"]}
        recovery_attempts = min(MAX_RECOVERED_RUNS, planned) * (1 + er.P1_RATE_LIMIT_RETRIES)
        row["recovery_max_p1_calls"] = recovery_attempts
        row["recovery_max_p1_tokens"] = recovery_attempts * er.P1_TOKENS_CEILING
        if gt_index is not None:
            per_video = er.judge_cap_required(config, split, gt_index)["per_video"]
            worst = sorted(per_video.values(), reverse=True)[:MAX_RECOVERED_RUNS]
            row["judge_required"] = er.judge_cap_required(config, split, gt_index)["required"]
            row["recovery_max_judge_calls"] = sum(worst) * er.JUDGE_ATTEMPTS_PER_FIELD
        rows[name] = row
    keys = sorted({k for r in rows.values() for k in r if k != "judge_required"})
    return {"configs": rows, "stage_total": {k: sum(r.get(k, 0) for r in rows.values()) for k in keys}}


def build_manifest(configs: dict[str, dict], split: dict, *, registry: dict | None = None,
                   config_dir: Path = CONFIG_DIR, gt_manifest_path: Path = GT_MANIFEST_PATH) -> dict:
    """Every pinned Stage 3 input. Deterministic (no timestamps), so a rebuild must equal the committed copy."""
    from eval_vlm_client import P1_RETRY_POLICIES, p1_request_config

    gt = json.loads(gt_manifest_path.read_text())
    request = p1_request_config()
    schema = request.pop("response_format")
    order = er.schedule(list(configs.values()), sorted(split["test"]), 1)
    policy = P1_RETRY_POLICIES["retry-v2"]
    return {
        "manifest": "stage3-manifest-v1",
        "selection_record": SELECTION_RECORD,
        "selected_prompt": selected_prompt(),
        "configs": {name: {"experiment_id": c["experiment_id"], "file": f"experiments/configs/{c['experiment_id']}.json",
                           "file_sha256": hashlib.sha256((config_dir / f"{c['experiment_id']}.json").read_bytes()).hexdigest(),
                           "arm": c["arm"], "prompt_id": c["prompt_id"],
                           "prompt_sha256": prompt_registry.entry(c["prompt_id"], registry)["sha256"]}
                    for name, c in configs.items()},
        "model": sorted({c["model"] for c in configs.values()}),
        "p1_request": {"settings": request, "response_format_sha256": sha256_text(json.dumps(schema, sort_keys=True)),
                       "contract_version": contract.contract_version()},
        "ground_truth": {"version": gt["version"], "status": gt["status"], "records_sha256": gt["records_sha256"],
                         "manifest_sha256": hashlib.sha256(gt_manifest_path.read_bytes()).hexdigest(),
                         "dir": sorted({c["ground_truth"]["dir"] for c in configs.values()})},
        "methodology": {"version": methodology.METHODOLOGY_VERSION, "match_threshold": methodology.MATCH_THRESHOLD,
                        "embedding_model": methodology.EMBEDDING_MODEL, "judge_model": methodology.JUDGE_MODEL,
                        "judge_prompt_version": methodology.JUDGE_PROMPT_VERSION,
                        "judge_settings": methodology.JUDGE_REQUEST_SETTINGS,
                        "timestamp_tolerance_seconds": methodology.TIMESTAMP_TOLERANCE_SECONDS,
                        "bootstrap": {"seed": methodology.BOOTSTRAP_SEED, "resamples": methodology.BOOTSTRAP_RESAMPLES},
                        "severity_reporting": "evaluation-methodology-v1.3 (reporting only)",
                        "comparison_metric": "D9 v2 (experiment_selection.compare; no selection on test)"},
        "split": {"version": split["version"], "seed": split.get("seed"), "half": "test", "clips": len(split["test"]),
                  "test": sorted(split["test"]), "test_sha256": sha256_text(json.dumps(sorted(split["test"])))},
        "order": {"rule": "D10: per repeat shuffled with random.Random(seed + repeat); arms interleaved per video, "
                          "first arm rotating by position", "seed": er.ORDER_SEED, "repeats": 1,
                  "video_runs": len(order), "schedule_sha256": sha256_text(json.dumps(order))},
        "retry_policy": {k: list(v) if isinstance(v, tuple) else v for k, v in policy.items()},
        "recovery": {"protocol": rec.PROTOCOL, "retry_policy": rec.RECOVERY_RETRY_POLICY,
                     "recoverable": list(rec.RECOVERABLE), "max_runs_per_config": MAX_RECOVERED_RUNS},
        "caps": stage_caps(configs, split),
        "p1_tokens_ceiling_per_attempt": er.P1_TOKENS_CEILING,
    }


# --- preflight ------------------------------------------------------------------------------------

def role_problems(configs: dict[str, dict], record: str = SELECTION_RECORD) -> list[str]:
    problems = []
    for name, (arm, prompt) in ROLES.items():
        config = configs.get(name)
        if config is None:
            problems.append(f"{name} is missing")
            continue
        want = prompt_registry.BASE_ID if prompt == "base" else selected_prompt(record)
        if config["arm"] != arm:
            problems.append(f"{name} must be the {arm} arm, not {config['arm']}")
        if config["prompt_id"] != want:
            problems.append(f"{name} must use {want}, not {config['prompt_id']}")
        if config["split"] != "test" or config["final"] is not True or config["selection_record"] != record:
            problems.append(f"{name} must be a final test config naming {record!r}")
        if config["frozen_baseline"] is not True:
            problems.append(f"{name} must be frozen_baseline (a test config runs once)")
        if config["repeats"] != 1:
            problems.append(f"{name} must have 1 repeat (owner, 2026-10-29)")
    return problems


def shared_setting_problems(configs: dict[str, dict]) -> list[str]:
    """C1-C4 share every setting that is not the arm or the prompt (plan §F.4)."""
    def shared(config):
        out = {k: v for k, v in config.items() if k not in PER_CONFIG_KEYS}
        out["pipeline"] = {k: v for k, v in config["pipeline"].items() if k != "agent_base_url"}
        return json.dumps(out, sort_keys=True)

    return [] if len({shared(c) for c in configs.values()}) == 1 else ["C1-C4 differ in a setting that is not under test"]


def manifest_problems(committed: dict, fresh: dict) -> list[str]:
    return [f"manifest drift in {key!r}: committed {json.dumps(committed.get(key))[:160]} vs now "
            f"{json.dumps(fresh.get(key))[:160]}" for key in sorted(set(committed) | set(fresh))
            if committed.get(key) != fresh.get(key)]


def body_difference(direct: dict, vss: dict) -> list[str]:
    """Keys whose values differ between the two arms' P1 bodies, apart from the allowed transport keys."""
    keys = (set(direct) | set(vss)) - TRANSPORT_KEYS
    return sorted(k for k in keys if json.dumps(direct.get(k), sort_keys=True) != json.dumps(vss.get(k), sort_keys=True))


AGENT_BODY_SCRIPT = """
import json, sys
from vss_agents.tools import incident_experiments
from vss_agents.tools.incident_report_gen import p1_request_body
model, url, prompt_id = sys.argv[1:4]
if prompt_id == "p1-v4-base":
    body = p1_request_body(model, url)  # the agent sends no experiment_prompt_id for the base prompt
else:
    text, _ = incident_experiments.resolve_prompt(prompt_id)
    body = p1_request_body(model, url, None, text)
print(json.dumps(body))
"""


def agent_body(model: str, prompt_id: str, *, python: Path = AGENT_PYTHON, agent_dir: Path = AGENT_DIR) -> dict:
    """The agent's P1 body for a prompt, built in the agent's own venv (no server, no request)."""
    env = {**os.environ, "INCIDENT_EXPERIMENTS_ENABLED": "1"}  # this subprocess only; it serves nothing
    out = subprocess.run([str(python), "-c", AGENT_BODY_SCRIPT, model, PARITY_URL, prompt_id], cwd=agent_dir, env=env,
                         capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def parity(configs: dict[str, dict], *, agent=agent_body) -> dict:
    """C1 and C2 send the same baseline request, C3 and C4 the same selected-prompt request."""
    from eval_vlm_client import p1_request_payload

    out = {}
    for direct, vss in (("C1", "C2"), ("C4", "C3")):
        config = configs[direct]
        text = prompt_registry.prompt_text(config["prompt_id"])
        mine = p1_request_payload(config["model"], PARITY_URL, text)
        theirs = agent(configs[vss]["model"], configs[vss]["prompt_id"])
        out[f"{vss}={direct}"] = {"prompt_id": config["prompt_id"], "differences": body_difference(mine, theirs),
                                  "transport_only": sorted((set(mine) ^ set(theirs)) & TRANSPORT_KEYS),
                                  "body_sha256_without_transport": sha256_text(json.dumps(
                                      {k: v for k, v in mine.items() if k not in TRANSPORT_KEYS}, sort_keys=True))}
    return out


def clip_problems(split: dict, dataset_manifest: dict, gt_index: dict) -> list[str]:
    clips = {c["incident_id"]: c for c in dataset_manifest["clips"]}
    problems = [f"{v}: not in the dataset manifest" for v in split["test"] if v not in clips]
    problems += [f"{v}: no R2 key or duration" for v in split["test"] if v in clips
                 and not (clips[v].get("r2_key") and clips[v].get("duration_seconds"))]
    problems += [f"{v}: not in the frozen ground truth" for v in split["test"] if v not in gt_index["by_incident_id"]]
    problems += [f"{v}: also in dev" for v in split["test"] if v in set(split["dev"])]
    return problems


def cap_problems(configs: dict[str, dict], split: dict, gt_index: dict) -> list[str]:
    problems = []
    for name, config in configs.items():
        planned = er.planned_calls(config, split)
        attempts = planned * (1 + er.P1_RATE_LIMIT_RETRIES)
        if config["budget"]["max_p1_calls"] != attempts:
            problems.append(f"{name}: max_p1_calls {config['budget']['max_p1_calls']} != {attempts} (every run x 3)")
        if config["budget"]["max_p1_tokens"] != attempts * er.P1_TOKENS_CEILING:
            problems.append(f"{name}: max_p1_tokens is not attempts x {er.P1_TOKENS_CEILING}")
        required = er.judge_cap_required(config, split, gt_index)["required"]
        if config["budget"]["max_judge_calls"] != required:
            problems.append(f"{name}: max_judge_calls {config['budget']['max_judge_calls']} != derived {required}")
    return problems


def run_once_problems(configs: dict[str, dict], results_root: Path = er.RESULTS_ROOT) -> list[str]:
    return [f"{name}: {config['experiment_id']} already has a completed run" for name, config in configs.items()
            if er.completed_runs(config["experiment_id"], results_root)]


def expected_usage(configs: dict[str, dict], split: dict, gt_index: dict) -> dict:
    """An estimate from Stage 2 rates (not a cap): metered P1 tokens, judge calls and runtime."""
    runs = sum(er.planned_calls(c, split) for c in configs.values())
    p1 = sum(er.planned_calls(c, split) * MEASURED["p1_tokens_per_call"][c["prompt_id"]] for c in configs.values())
    fields = sum(er.judge_cap_required(c, split, gt_index)["judged_fields"] for c in configs.values())
    judge = round(fields * MEASURED["judge_calls_per_judged_field"])
    low, high = MEASURED["video_runs_per_hour"]
    extra = MEASURED["extra_attempt_share"]
    return {"video_runs": runs, "p1_attempts": [round(runs * (1 + e)) for e in extra], "p1_tokens": p1,
            "judge_calls": judge, "judge_tokens": judge * MEASURED["judge_tokens_per_call"],
            "runtime_hours": [round(runs / high, 1), round(runs / low, 1)], "basis": MEASURED}


def preflight_checks(*, skip_agent_parity: bool = False, results_root: Path = er.RESULTS_ROOT) -> dict:
    """Every offline Stage 3 check (``eval_stage3.py preflight``; the supervisor repeats it before each session)."""
    import eval_experiment

    configs, split = load_configs(), json.loads(er.SPLIT_PATH.read_text())
    gt_index, _ = eval_experiment.load_gt(configs["C1"])
    checks = {"roles": role_problems(configs), "shared settings": shared_setting_problems(configs),
              "runner guards": [f"{n}: {p}" for n, c in configs.items() for p in er.config_problems(c)]}
    try:
        for config in configs.values():
            er.preflight(config, split, results_root=results_root)
    except er.ExperimentRefused as exc:
        checks["runner guards"].append(str(exc))
    committed = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
    checks["manifest"] = manifest_problems(committed, build_manifest(configs, split)) if committed \
        else ["experiments/stage3/manifest.json is missing"]
    checks["ground truth"] = [] if gt_index["manifest"].get("records_sha256") == committed.get("ground_truth", {}).get(
        "records_sha256") else ["the loaded frozen ground truth does not match the manifest digest"]
    checks["test clips"] = clip_problems(split, json.loads(eval_experiment.DATASET_MANIFEST.read_text()), gt_index)
    checks["caps"] = cap_problems(configs, split, gt_index)
    checks["run once"] = run_once_problems(configs, results_root)
    request_parity = None
    if skip_agent_parity:
        checks["request parity"] = ["skipped (--skip-agent-parity): not a passing preflight"]
    else:
        request_parity = parity(configs)
        checks["request parity"] = [f"{pair}: {row['differences']}" for pair, row in request_parity.items()
                                    if row["differences"]]
    return {"ok": not any(checks.values()), "checks": checks, "request_parity": request_parity,
            "caps": stage_caps(configs, split, gt_index), "expected": expected_usage(configs, split, gt_index)}


# --- report ---------------------------------------------------------------------------------------

COMPARISONS = (*er.COMPARISONS, ("C3-C1", "C3", "C1", ("best VSS vs fixed direct baseline = (C3-C4) + (C4-C1); "
                                                        "never an architecture claim")))
PROMPT_COMPARISONS = ("C3-C2", "C4-C1")
# D15: test clips named in recorded prompt-design pilots. The 52-clip remainder is reported too; it is not unseen.
PILOT_CLIPS = ("Animal003", "Assault018", "Burglary005")


def without_pilot_clips(record: dict) -> dict:
    return {**record, "videos": [v for v in record["videos"] if v["incident_id"] not in PILOT_CLIPS]}


def timing(record: dict) -> dict:
    """Model processing (P1 round trip to the gateway), pipeline overhead and end-to-end, in seconds."""
    model, overhead, end_to_end = [], [], []
    for video in record["videos"]:
        transport = video.get("transport") or {}
        if record["arm"] == "vss":
            p1 = transport.get("p1_elapsed_ms")
            if p1 is not None:
                model.append(p1 / 1000.0)
            if transport.get("end_to_end_s") is not None:
                end_to_end.append(transport["end_to_end_s"])
                if p1 is not None:
                    overhead.append(transport["end_to_end_s"] - p1 / 1000.0)
        elif (video.get("timing") or {}).get("p1_elapsed_s") is not None:
            model.append(video["timing"]["p1_elapsed_s"])

    def stats(values):
        return {"n": len(values), "p50": experiment_report._percentile(values, 0.5),
                "p95": experiment_report._percentile(values, 0.95),
                "mean": round(sum(values) / len(values), 2) if values else None}

    return {"model_processing": stats(model), "pipeline_overhead": stats(overhead), "end_to_end": stats(end_to_end),
            "note": "direct: harness-to-gateway P1 round trip; VSS: the agent's P1 round trip, plus its overhead"}


def failures(record: dict) -> dict:
    out = {}
    for video in record["videos"]:
        if video["outcome"] == "scored":
            continue
        cause = rec.failure_class(video) or ("invalid_model_output" if extraction_stats.has_model_output(video)
                                             else video["outcome"])
        out.setdefault(f"{video['outcome']} ({cause})", []).append(video["incident_id"])
    return out


def per_category(base: dict, cand: dict) -> dict:
    a, b = es.per_video(base), es.per_video(cand)
    categories = {v["incident_id"]: v["category"] for v in base["videos"]}
    out = {}
    for category in sorted(set(categories.values())):
        ids = sorted(i for i, c in categories.items() if c == category and i in a and i in b)
        d = es.deltas(a, b, ids)
        out[category] = {"videos": len(ids), "primary": None if d["primary"] is None else round(d["primary"], 4),
                         **{k: None if d[k] is None else round(d[k], 4) for k in es.COMPONENTS}}
    return out


def examples(base: dict, cand: dict, n: int = 3) -> dict:
    """The clips with the largest per-video ΔI gains and regressions (representative cases, not a selection)."""
    a, b = es.per_video(base), es.per_video(cand)
    categories = {v["incident_id"]: v["category"] for v in base["videos"]}
    rows = []
    for vid in sorted(set(a) & set(b)):
        d = es.deltas(a, b, [vid])
        if d["primary"] is not None:
            rows.append({"incident_id": vid, "category": categories.get(vid), "delta_i": round(d["primary"], 4),
                         **{k: None if d[k] is None else round(d[k], 4) for k in es.COMPONENTS}})
    rows.sort(key=lambda r: (r["delta_i"], r["incident_id"]))
    return {"gains": rows[::-1][:n], "regressions": [r for r in rows[:n] if r["delta_i"] < 0],
            "unchanged": sum(1 for r in rows if r["delta_i"] == 0)}


def report(records: dict[str, dict]) -> dict:
    out = {"problems": er.configuration_problems(records), "reportable": all(r.get("reportable") for r in records.values()),
           "configs": {}, "comparisons": {}}
    for name, record in records.items():
        out["configs"][name] = {"experiment_id": record["experiment_id"], "protocol": record.get("protocol", "original"),
                                "reliability": record.get("reliability") or extraction_stats.reliability(record["videos"]),
                                "reliability_original": record.get("reliability_original"),
                                "severity": severity_metrics.summarise(record["videos"]), "timing": timing(record),
                                "usage": experiment_report.usage(record), "items": experiment_report.items(record),
                                "failures": failures(record)}
    for name, minuend, subtrahend, meaning in COMPARISONS:
        if minuend not in records or subtrahend not in records:
            continue
        base, cand = records[subtrahend], records[minuend]
        comparison = es.compare(base, cand)
        row = {"meaning": meaning, "d9": comparison, "severity": severity_metrics.paired(base["videos"], cand["videos"]),
               "per_category": per_category(base, cand), "examples": examples(base, cand),
               "d9_excluding_pilot_clips": es.compare(without_pilot_clips(base), without_pilot_clips(cand))}
        if name in PROMPT_COMPARISONS:
            # Informational only: Stage 3 selects nothing. Reported so a held-out regression is visible.
            row["guardrails_informational"] = es.guardrails(base, cand, comparison)
        out["comparisons"][name] = row
    return out


def _ci(interval) -> str:
    return "–" if not interval else f"[{interval[0]:+.3f}, {interval[1]:+.3f}]"


def _num(value) -> str:
    return "–" if value is None else f"{value:+.3f}"


def render(summary: dict, records: dict[str, dict], *, title: str) -> str:
    """Markdown: the shared experiment report (conditional and end-to-end fields, items, reliability, usage),
    then the Stage 3 sections."""
    lines = [experiment_report.render(records, title=title).rstrip(), "", "## Stage 3: D9 v2 paired differences",
             "", "Per video (one repeat), 95% video-cluster bootstrap. A difference, never a selection on test.", "",
             "| Comparison | Measures | Videos | ΔI | 95% CI | Incident | Entity F1 | Object F1 | ΔI8 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, row in summary["comparisons"].items():
        p, ci = row["d9"]["point"], row["d9"]["ci95"]
        lines.append(f"| {name} | {row['meaning']} | {row['d9']['videos']} | {_num(p['primary'])} | {_ci(ci['primary'])} "
                     f"| {_num(p['incident'])} | {_num(p['entity_f1'])} | {_num(p['object_f1'])} | {_num(p['eight'])} |")
    lines += ["", "### Excluding the clips named in recorded prompt-design pilots (D15; not an unseen subset)", "",
              f"Excludes {', '.join(PILOT_CLIPS)}. All remaining clips were in the 2026-10-02 benchmark.", "",
              "| Comparison | Videos | ΔI | 95% CI |", "|---|---|---|---|"]
    for name, row in summary["comparisons"].items():
        sub = row["d9_excluding_pilot_clips"]
        lines.append(f"| {name} | {sub['videos']} | {_num(sub['point']['primary'])} | {_ci(sub['ci95']['primary'])} |")
    lines += ["", "### Per score", "", "| Comparison | " + " | ".join(es.EIGHT_SCORES) + " |",
              "|---|" + "---|" * len(es.EIGHT_SCORES)]
    for name, row in summary["comparisons"].items():
        p, ci = row["d9"]["point"], row["d9"]["ci95"]
        lines.append(f"| {name} | " + " | ".join(f"{_num(p[s])} {_ci(ci[s])}" for s in es.EIGHT_SCORES) + " |")
    lines += ["", "### Guardrails on the prompt comparisons (informational; nothing is selected on test)", ""]
    for name in PROMPT_COMPARISONS:
        if name in summary["comparisons"]:
            lines.append(f"- {name}: {summary['comparisons'][name]['guardrails_informational'] or 'none'}")
    lines += ["", "## Stage 3: severity (methodology v1.3, reporting only)", "",
              "| Config | Valid | MAE | Signed error | Exact | Within ±1 | Over / under |", "|---|---|---|---|---|---|---|"]
    for name, cfg in summary["configs"].items():
        s = cfg["severity"]
        lines.append(f"| {name} | {s.get('valid')} | {s.get('mae')} | {s.get('mean_signed_error')} | {s.get('exact')} | "
                     f"{s.get('within_one')} | {s.get('over_rated')} / {s.get('under_rated')} |")
    lines += ["", "| Comparison | Pairs | MAE difference | 95% CI | Signed-error difference | 95% CI |",
              "|---|---|---|---|---|---|"]
    for name, row in summary["comparisons"].items():
        s = row["severity"]
        lines.append(f"| {name} | {s['pairs']} | {_num(s['mae_difference'])} | {_ci(s['mae_difference_ci95'])} | "
                     f"{_num(s['signed_error_difference'])} | {_ci(s['signed_error_difference_ci95'])} |")
    categories = sorted({c for row in summary["comparisons"].values() for c in row["per_category"]})
    lines += ["", "## Stage 3: ΔI per category (descriptive; 10-13 clips each)", "",
              "| Comparison | " + " | ".join(categories) + " |", "|---|" + "---|" * len(categories)]
    for name, row in summary["comparisons"].items():
        lines.append(f"| {name} | " + " | ".join(_num((row["per_category"].get(c) or {}).get("primary"))
                                                  for c in categories) + " |")
    lines += ["", "## Stage 3: latency (seconds)", "",
              "| Config | Model processing p50 / p95 | Pipeline overhead p50 / p95 | End-to-end p50 / p95 |",
              "|---|---|---|---|"]
    for name, cfg in summary["configs"].items():
        t = cfg["timing"]
        lines.append(f"| {name} | " + " | ".join(f"{t[k]['p50']} / {t[k]['p95']} (n {t[k]['n']})"
                                                  for k in ("model_processing", "pipeline_overhead", "end_to_end")) + " |")
    lines += ["", "- Direct: model processing is the harness-to-gateway P1 round trip; there is no pipeline stage.",
              "- VSS: model processing is the agent's own P1 round trip; overhead is `/analyze` end-to-end minus it.",
              "", "## Stage 3: reliability and failures", "",
              "| Config | Protocol | Reliability | Original-run reliability | Failures |", "|---|---|---|---|---|"]
    for name, cfg in summary["configs"].items():
        r, o = cfg["reliability"], cfg["reliability_original"]
        lines.append(f"| {name} | {cfg['protocol']} | {r['outcomes']} | {o['outcomes'] if o else '(this record)'} | "
                     f"{cfg['failures'] or 'none'} |")
    lines += ["", "## Stage 3: representative clips (largest per-video ΔI changes)", ""]
    for name, row in summary["comparisons"].items():
        ex = row["examples"]
        gains = ", ".join(f"{r['incident_id']} {r['delta_i']:+.3f}" for r in ex["gains"]) or "none"
        regressions = ", ".join(f"{r['incident_id']} {r['delta_i']:+.3f}" for r in ex["regressions"]) or "none"
        lines.append(f"- **{name}:** gains {gains}; regressions {regressions}; unchanged {ex['unchanged']}")
    lines += ["", "## Stage 3: interpretation", "",
              ("- **Same model, same prompts:** both arms use Cosmos 3 Super and send the same P1 body at one prompt. "
               "A VSS-minus-direct difference (C2-C1, C3-C4) is a pipeline, transport or run-to-run effect, never an "
               "architectural extraction advantage."),
              ("- **Ground truth:** `ground-truth-v1.0` is frozen on dataset-level approval of AI-assisted labels; not "
               "individually human-verified. τ = 0.40 is AI-calibrated, not human-validated."),
              ("- **Exposure:** the 55 test clips are held out from Stage 2 selection but not unseen: they were in the "
               "2026-10-02 benchmark, and three shaped earlier prompt pilots.")]
    if summary["problems"]:
        lines += ["", f"**Configuration problems:** {summary['problems']}"]
    return "\n".join(lines) + "\n"
