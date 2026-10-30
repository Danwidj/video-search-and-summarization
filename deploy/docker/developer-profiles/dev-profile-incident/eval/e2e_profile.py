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

"""The end-to-end VSS profile (plan §F.2): C2 and C3 through VSS with cropping on, latency and reliability only.

Two configs (``experiments/configs/e2e-*.json``) run the Stage 3 C2 and C3 settings on 15 test clips (3 per
category, seeded) with cropping on under a per-request cap of grounding calls, and are never scored. This
module pins their inputs (``experiments/e2e-profile/manifest.json``), checks them offline, and reports
latency (end to end, P1, cropping, other overhead), the cropping stage and reliability.

**Stage 3 is read-only here:** the profile has its own experiment ids, results and stage directory, and the
preflight and the report both check that every Stage 3 result file still has the hash its audit recorded.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import subprocess
from pathlib import Path

import experiment_runner as er
import prompt_registry
import stage3

EVAL_DIR = Path(__file__).resolve().parent
CONFIG_DIR = EVAL_DIR / "experiments" / "configs"
MANIFEST_PATH = EVAL_DIR / "experiments" / "e2e-profile" / "manifest.json"
STAGE3_REPORTS = EVAL_DIR / "eval_data" / "results" / "reports" / "stage3"
CONFIGS = {"C2": "e2e-c2-vss-base", "C3": "e2e-c3-vss-v1"}
STAGE3_COUNTERPART = {"C2": "s3-c2-vss-base", "C3": "s3-c3-vss-v1"}
CLIP_SEED = 20261027
CLIPS_PER_CATEGORY = 3
CROP_CALLS_PER_REQUEST = 40
# Settings a profile config keeps from its Stage 3 counterpart (everything that is not the profile itself).
SHARED_WITH_STAGE3 = ("arm", "prompt_id", "model", "ground_truth", "split", "repeats", "selection_record")
SHARED_PIPELINE = ("skip_rp1", "agent_base_url", "retry_policy")
FRAME_CHECK_SCRIPT = """
import json, os, sys
from vss_agents.api.incident_analyze import AnalyzeIncidentRequest
from vss_agents.tools.incident_report_gen import IncidentReportGenInput, experiment_settings
from vss_agents.utils import crop_evidence
from vss_agents.utils.r2 import is_r2_configured
payload, clip = json.loads(sys.argv[1]), sys.argv[2]
request = AnalyzeIncidentRequest(**payload)
tool = {k: v for k, v in payload.items() if k in IncidentReportGenInput.model_fields}
settings = experiment_settings(IncidentReportGenInput(incident_id="preflight", **tool), None)
frame = crop_evidence.extract_frame(clip, 1)
print(json.dumps({"experimental": request.is_experimental(), "max_crop_calls": settings["max_crop_calls"],
                  "skip_crops": settings["skip_crops"], "persisted": settings["persisted"],
                  "r2_configured": is_r2_configured(), "frame_shape": None if frame is None else list(frame.shape)}))
"""


def load_configs(directory: Path = CONFIG_DIR) -> dict[str, dict]:
    return {name: er.load_config(directory / f"{eid}.json") for name, eid in CONFIGS.items()}


def select_clips(split: dict, seed: int = CLIP_SEED, per_category: int = CLIPS_PER_CATEGORY) -> list[str]:
    """3 test clips per category: ``random.Random(seed).sample(sorted(category test clips), 3)`` per category."""
    picked = []
    for category in sorted(split["by_category"]):
        picked += random.Random(seed).sample(sorted(split["by_category"][category]["test"]), per_category)
    return sorted(picked)


def stage3_audit(reports: Path = STAGE3_REPORTS) -> tuple[Path, dict]:
    audits = sorted(reports.glob("audit-*.json"))
    if not audits:
        raise FileNotFoundError(f"no Stage 3 audit under {reports}")
    return audits[-1], json.loads(audits[-1].read_text())


def stage3_problems(reports: Path = STAGE3_REPORTS) -> list[str]:
    """Every Stage 3 result file still has the SHA-256 its passed audit recorded (read only)."""
    try:
        path, audit = stage3_audit(reports)
    except FileNotFoundError as exc:
        return [str(exc)]
    problems = [] if audit.get("ok") else [f"{path.name} did not pass"]
    for file, digest in sorted(audit.get("files_sha256", {}).items()):
        if not Path(file).exists():
            problems.append(f"{file}: missing")
        elif stage3.rec.sha256_file(Path(file)) != digest:
            problems.append(f"{file}: changed since the Stage 3 audit")
    return problems


def caps(configs: dict[str, dict]) -> dict:
    keys = (*er.BUDGET_KEYS, *er.CROP_BUDGET_KEYS)
    per = {name: {k: c["budget"][k] for k in keys} for name, c in configs.items()}
    return {"per_config": per, "stage": {k: sum(p[k] for p in per.values()) for k in keys},
            "max_crop_calls_per_request": sorted({c["pipeline"]["max_crop_calls_per_request"]
                                                  for c in configs.values()}),
            "crop_tokens_ceiling_per_call": er.CROP_TOKENS_CEILING, "p1_tokens_ceiling_per_attempt": er.P1_TOKENS_CEILING}


def build_manifest(configs: dict[str, dict], split: dict, *, config_dir: Path = CONFIG_DIR) -> dict:
    """Every pinned profile input. Deterministic, so a rebuild must equal the committed copy."""
    agent_dir = stage3.AGENT_DIR / "src" / "vss_agents"
    order = er.schedule(list(configs.values()), select_clips(split), 1)
    _, audit = stage3_audit()
    return {
        "manifest": "e2e-profile-manifest-v1",
        "plan": "ground-truth-and-prompt-experiments-plan §F.2 (end-to-end profile; latency and reliability only)",
        "configs": {name: {"experiment_id": c["experiment_id"], "file": f"experiments/configs/{c['experiment_id']}.json",
                           "file_sha256": stage3.rec.sha256_file(config_dir / f"{c['experiment_id']}.json"),
                           "stage3_counterpart": STAGE3_COUNTERPART[name], "prompt_id": c["prompt_id"],
                           "prompt_sha256": prompt_registry.entry(c["prompt_id"])["sha256"]}
                    for name, c in configs.items()},
        "clips": {"rule": f"per category, random.Random({CLIP_SEED}).sample(sorted test clips, {CLIPS_PER_CATEGORY})",
                  "seed": CLIP_SEED, "test": select_clips(split)},
        "order": {"seed": er.ORDER_SEED, "video_runs": len(order), "schedule_sha256": stage3.sha256_text(json.dumps(order))},
        "caps": caps(configs),
        "agent_code_sha256": {p: stage3.rec.sha256_file(agent_dir / p) for p in
                              ("utils/crop_evidence.py", "tools/incident_report_gen.py", "api/incident_analyze.py")},
        "stage3_protected": {"audit_at": audit.get("at"), "files_sha256": audit.get("files_sha256", {})},
    }


def manifest_problems(committed: dict, fresh: dict) -> list[str]:
    return [f"{key}: differs from the committed manifest" for key in sorted(set(committed) | set(fresh))
            if committed.get(key) != fresh.get(key)]


def setting_problems(configs: dict[str, dict], split: dict) -> list[str]:
    """Each profile config is its Stage 3 counterpart plus cropping, on the 15 seeded clips."""
    problems = []
    s3 = stage3.load_configs()
    clips = select_clips(split)
    counterpart = {"C2": s3["C2"], "C3": s3["C3"]}
    for name, config in configs.items():
        for key in SHARED_WITH_STAGE3:
            if config[key] != counterpart[name][key]:
                problems.append(f"{name}: {key} differs from its Stage 3 counterpart")
        for key in SHARED_PIPELINE:
            if config["pipeline"].get(key) != counterpart[name]["pipeline"].get(key):
                problems.append(f"{name}: pipeline.{key} differs from its Stage 3 counterpart")
        if config["videos"] != clips:
            problems.append(f"{name}: videos are not the 15 seeded clips {clips}")
        if config["pipeline"].get("max_crop_calls_per_request") != CROP_CALLS_PER_REQUEST:
            problems.append(f"{name}: the crop-call cap is not {CROP_CALLS_PER_REQUEST}")
        if config["experiment_id"] in stage3.CONFIGS.values():
            problems.append(f"{name}: uses a Stage 3 experiment id")
    if stage3.selected_prompt() != configs["C3"]["prompt_id"] or configs["C2"]["prompt_id"] != prompt_registry.BASE_ID:
        problems.append("C2 must use the base prompt and C3 the selected prompt")
    by_category = {}
    for clip in clips:
        category = next(c for c, v in split["by_category"].items() if clip in v["test"])
        by_category[category] = by_category.get(category, 0) + 1
    if sorted(by_category.values()) != [CLIPS_PER_CATEGORY] * len(split["by_category"]):
        problems.append(f"clips per category are {by_category}")
    return problems


def runner_payload(config: dict) -> dict:
    """The ``/analyze`` body the runner sends for a profile config (``experiment_runner.vss_call``)."""
    payload = {"video_url": stage3.PARITY_URL, "model": config["model"], "model_run_id": "preflight", "skip_rp1": True,
               "skip_crops": config["pipeline"]["skip_crops"],
               "max_crop_calls": config["pipeline"]["max_crop_calls_per_request"]}
    if config["prompt_id"] != prompt_registry.BASE_ID:
        payload["experiment_prompt_id"] = config["prompt_id"]
    return payload


def local_clip(incident_id: str) -> Path | None:
    hits = sorted((EVAL_DIR / "eval_data" / "videos").glob(f"*/{incident_id}_x264*.mp4"))
    return hits[0] if hits else None


def agent_check(config: dict, clip: Path, *, python: Path = stage3.AGENT_PYTHON, agent_dir: Path = stage3.AGENT_DIR):
    """In the agent's own venv (no server, no request): the agent accepts the runner's body as an experimental
    crops-on request with its cap, and its crop stage can read a frame of a local copy of a profile clip."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("R2_", "SUPABASE", "DATABASE_URL"))}
    env["INCIDENT_EXPERIMENTS_ENABLED"] = "1"  # this subprocess only; it serves nothing
    out = subprocess.run([str(python), "-c", FRAME_CHECK_SCRIPT, json.dumps(runner_payload(config)), str(clip)],
                         cwd=agent_dir, env=env, capture_output=True, text=True, timeout=180, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def stage3_items(clips: list[str]) -> dict[str, dict[str, int]]:
    """Predicted items per clip in the Stage 3 C2 and C3 results (read only): the crop-call estimate."""
    _, audit = stage3_audit()
    out = {}
    for name, eid in STAGE3_COUNTERPART.items():
        path = next(Path(f) for f in audit["files_sha256"] if f"/{eid}/" in f and f.endswith("/results.json"))
        videos = json.loads(path.read_text())["videos"]
        out[name] = {v["incident_id"]: sum(len((v.get("prediction") or {}).get(k) or [])
                                           for k in ("entities", "instruments", "assets"))
                     for v in videos if v["incident_id"] in clips}
    return out


def expected_usage(configs: dict[str, dict], split: dict) -> dict:
    """Planning estimate from Stage 3 (offline): P1 as measured there, one crop call per predicted item up to the cap."""
    clips = select_clips(split)
    items = stage3_items(clips)
    out = {}
    for name, config in configs.items():
        cap = config["pipeline"]["max_crop_calls_per_request"]
        calls = sum(min(n, cap) for n in items[name].values())
        tokens_per_call = stage3.MEASURED["p1_tokens_per_call"][config["prompt_id"]]
        out[name] = {"p1_attempts": [len(clips), round(len(clips) * (1 + stage3.MEASURED["extra_attempt_share"][1]))],
                     "p1_tokens": len(clips) * tokens_per_call,
                     "crop_calls_from_stage3_items": calls, "items_beyond_cap": sum(max(0, n - cap) for n in items[name].values()),
                     "crop_calls_range": [calls, round(calls * 1.15)], "crop_tokens_range": [calls * 1500, round(calls * 1.15) * 4000]}
    return {"per_config": out, "items_per_clip_in_stage3": items,
            "note": "crop tokens per call are not measured yet (1,500-4,000 assumed); the caps bound them at "
                    f"{er.CROP_TOKENS_CEILING} per call"}


def preflight_checks(*, skip_agent_check: bool = False, results_root: Path = er.RESULTS_ROOT) -> dict:
    """Every offline profile check (``eval_e2e_profile.py preflight``). Sends no model, grounding or judge request."""
    configs, split = load_configs(), json.loads(er.SPLIT_PATH.read_text())
    checks = {"runner guards": [f"{n}: {p}" for n, c in configs.items() for p in er.config_problems(c)],
              "settings": setting_problems(configs, split), "stage 3 unchanged": stage3_problems()}
    try:
        for config in configs.values():
            er.preflight(config, split, results_root=results_root)
    except er.ExperimentRefused as exc:
        checks["runner guards"].append(str(exc))
    committed = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
    checks["manifest"] = manifest_problems(committed, build_manifest(configs, split)) if committed \
        else ["experiments/e2e-profile/manifest.json is missing"]
    checks["isolation"] = [f"{c['experiment_id']}: a results directory already exists"
                           for c in configs.values() if (results_root / c["experiment_id"]).exists()]
    agent = None
    if skip_agent_check:
        checks["agent"] = ["skipped (--skip-agent-check): not a passing preflight"]
    else:
        clip = next((p for p in map(local_clip, select_clips(split)) if p is not None), None)
        if clip is None:
            checks["agent"] = ["no local copy of a profile clip under eval_data/videos (eval_fetch_videos.py)"]
        else:
            agent = {name: agent_check(c, clip) for name, c in configs.items()}
            checks["agent"] = [f"{n}: {r}" for n, r in agent.items()
                               if not (r["experimental"] and r["max_crop_calls"] == CROP_CALLS_PER_REQUEST
                                       and r["skip_crops"] is False and r["persisted"] is False
                                       and not r["r2_configured"] and r["frame_shape"])]
    return {"ok": not any(checks.values()), "checks": checks, "agent": agent, "caps": caps(configs),
            "expected": expected_usage(configs, split)}


# --- report ---------------------------------------------------------------------------------------

def _stats(values: list[float]) -> dict:
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0, "p50": None, "p95": None, "mean": None}
    p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
    return {"n": len(values), "p50": round(statistics.median(values), 2), "p95": round(p95, 2),
            "mean": round(statistics.fmean(values), 2)}


def summarise(record: dict) -> dict:
    """Latency split (end to end, P1, cropping, the rest), the cropping stage and reliability of one profile config."""
    e2e, p1, crop, rest, calls, images, items, gaps, capped = [], [], [], [], [], 0, 0, {}, 0
    for video in record["videos"]:
        transport = video.get("transport") or {}
        stage = (transport.get("experiment") or {}).get("crop") or {}
        if transport.get("end_to_end_s") is None or video.get("outcome") != "scored":
            continue
        e2e.append(transport["end_to_end_s"])
        p1_s = (transport.get("p1_elapsed_ms") or 0) / 1000.0
        crop_s = (stage.get("elapsed_ms") or 0) / 1000.0
        p1.append(p1_s)
        crop.append(crop_s)
        rest.append(transport["end_to_end_s"] - p1_s - crop_s)
        calls.append(stage.get("calls") or 0)
        images += stage.get("images") or 0
        items += stage.get("items") or 0
        capped += 1 if stage.get("cap_reached") else 0
        for reason, n in (stage.get("gaps") or {}).items():
            gaps[reason] = gaps.get(reason, 0) + n
    return {"experiment_id": record["experiment_id"], "complete": record.get("complete"),
            "reliability": record.get("reliability"), "usage": record.get("usage"),
            "latency_s": {"end_to_end": _stats(e2e), "p1_inference": _stats(p1), "cropping": _stats(crop),
                          "other_overhead": _stats(rest)},
            "cropping": {"items": items, "images": images, "image_rate": round(images / items, 4) if items else None,
                         "gaps": gaps, "calls_per_request": _stats(calls), "requests_at_cap": capped}}


def report(records: dict[str, dict]) -> dict:
    problems = stage3_problems()
    for name, record in records.items():
        if record.get("purpose") != "profile" or record["experiment_id"] != CONFIGS[name]:
            problems.append(f"{name}: not the {CONFIGS[name]} profile record")
    return {"problems": problems, "configs": {n: summarise(r) for n, r in records.items()},
            "note": "latency and reliability only; outputs are never scored or compared for accuracy"}


def render(summary: dict, title: str) -> str:
    lines = [f"# {title}", "", "Latency and reliability only (plan §F.2): never an accuracy result.", ""]
    if summary["problems"]:
        lines += ["**Problems:**", *[f"- {p}" for p in summary["problems"]], ""]
    lines += ["| Config | Stage | n | p50 | p95 | mean |", "|---|---|---|---|---|---|"]
    for name, row in summary["configs"].items():
        for stage_name, s in row["latency_s"].items():
            lines.append(f"| {name} | {stage_name} | {s['n']} | {s['p50']} | {s['p95']} | {s['mean']} |")
    lines += ["", "| Config | Items | Images | Image rate | Calls per request p50 / p95 | At cap | Gaps | Reliability |",
              "|---|---|---|---|---|---|---|---|"]
    for name, row in summary["configs"].items():
        c, r = row["cropping"], row["reliability"] or {}
        lines.append(f"| {name} | {c['items']} | {c['images']} | {c['image_rate']} | {c['calls_per_request']['p50']} / "
                     f"{c['calls_per_request']['p95']} | {c['requests_at_cap']} | {c['gaps']} | {r.get('outcomes')} |")
    lines += ["", "| Config | P1 attempts | P1 tokens | Crop calls (bound) | Crop tokens (bound) | Judge calls |",
              "|---|---|---|---|---|---|"]
    for name, row in summary["configs"].items():
        u = row["usage"] or {}
        lines.append(f"| {name} | {u.get('p1_attempts')} | {u.get('p1_tokens')} | {u.get('crop_calls')} "
                     f"({u.get('crop_calls_bound')}) | {u.get('crop_tokens')} ({u.get('crop_tokens_bound')}) | "
                     f"{u.get('judge_calls')} |")
    return "\n".join(lines) + "\n"
