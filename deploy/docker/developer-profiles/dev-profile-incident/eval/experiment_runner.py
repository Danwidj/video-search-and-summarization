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

"""The two-arm prompt experiment runner (PR 6A; plan §F).

An experiment config (``eval/experiments/configs/<id>.json``) fixes one configuration:
the arm (``direct-vlm`` or ``vss``), a registry prompt, the model, the split half, the
frozen ground truth, the repeats and a call budget. Both arms send the same P1 request
(same prompt text, same ``inference.json`` settings, same signed URL), go through the same
rate-limit policy, and are re-validated by the same ``contract.evaluate_policy`` and the
same scorer, so a difference between them is a pipeline difference, not a scoring one.

Guards, all enforced before any call:
- **test split:** refused unless the config is ``final`` and names a selection record that
  exists in ``.docs/decisions.md`` (the prompt was chosen on dev before test is touched);
- **frozen baseline:** a config marked ``frozen_baseline`` with a completed run is never
  run again; its saved outputs are re-scored offline instead;
- **budget:** the planned P1 calls (videos x repeats) must fit ``budget.max_p1_calls``;
- **paid calls:** nothing is sent without ``confirm_paid`` (the CLI's ``--confirm-paid``);
  the default is a dry run that prints the plan;
- **ground truth:** a frozen ``ground-truth-v1.0`` only; a candidate needs the explicit
  plumbing flag and marks every result ``reportable: false``;
- **VSS prompt:** a non-production prompt counts only if the agent's response echoes the
  prompt id and SHA-256 it actually used; otherwise the attempt is ``request_failed``.

Results go to ``eval_data/results/experiments/<experiment_id>/<UTC time>/`` (immutable, gitignored).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import contract
import extraction_stats
import methodology
import prompt_registry

EVAL_DIR = Path(__file__).resolve().parent
PROFILE_DIR = EVAL_DIR.parent
CONFIG_DIR = EVAL_DIR / "experiments" / "configs"
RESULTS_ROOT = EVAL_DIR / "eval_data" / "results" / "experiments"
DECISIONS_PATH = PROFILE_DIR / ".docs" / "decisions.md"
SPLIT_PATH = EVAL_DIR / "eval_reproducibility" / "split-v2.json"
ARMS = ("direct-vlm", "vss")
SPLITS = ("dev", "test")
CONFIG_KEYS = {"experiment_id", "description", "arm", "prompt_id", "model", "split", "ground_truth", "repeats",
               "budget", "pipeline", "frozen_baseline", "final", "selection_record", "baseline_ref", "videos"}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,20}$")


class ExperimentRefused(RuntimeError):
    """A guard stopped the experiment before any call was made."""


# --- config ------------------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    return json.loads(path.read_text())


def allowed_models() -> set[str]:
    return {m["id"] for m in contract.load_inference()["models"]}


def selection_record_exists(heading: str, decisions_path: Path = DECISIONS_PATH) -> bool:
    return any(line.strip() == f"### {heading}".strip() for line in decisions_path.read_text().splitlines())


def config_problems(config: dict, *, registry: dict | None = None, decisions_path: Path = DECISIONS_PATH) -> list[str]:
    problems = []
    if set(config) != CONFIG_KEYS:
        problems.append(f"keys must be exactly {sorted(CONFIG_KEYS)}; got extra {sorted(set(config) - CONFIG_KEYS)}, "
                        f"missing {sorted(CONFIG_KEYS - set(config))}")
        return problems
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,60}", config["experiment_id"]):
        problems.append("experiment_id must be lower-case letters, digits and hyphens")
    if config["arm"] not in ARMS:
        problems.append(f"arm must be one of {ARMS}")
    try:
        prompt_registry.entry(config["prompt_id"], registry)
    except prompt_registry.RegistryError as exc:
        problems.append(str(exc))
    if config["model"] not in allowed_models():
        problems.append(f"model {config['model']!r} is not in the contracts/inference.json allowlist")
    if config["split"] not in SPLITS:
        problems.append(f"split must be one of {SPLITS}")
    if not isinstance(config["repeats"], int) or config["repeats"] < 1:
        problems.append("repeats must be a whole number >= 1")
    if not isinstance((config["budget"] or {}).get("max_p1_calls"), int):
        problems.append("budget.max_p1_calls must be a whole number")
    pipeline = config["pipeline"] or {}
    if pipeline.get("skip_rp1") is not True:
        problems.append("pipeline.skip_rp1 must be true: RP1 is not part of an extraction experiment")
    if pipeline.get("profile", "accuracy") == "accuracy" and pipeline.get("skip_crops") is not True:
        problems.append("pipeline.skip_crops must be true for an accuracy run (cropping is the end-to-end profile only)")
    if config["arm"] == "vss" and not pipeline.get("agent_base_url"):
        problems.append("a vss config needs pipeline.agent_base_url")
    if config["arm"] == "direct-vlm" and pipeline.get("agent_base_url"):
        problems.append("a direct-vlm config must not name an agent")
    if config["videos"] is not None and (not isinstance(config["videos"], list) or not config["videos"]):
        problems.append("videos must be null (the whole split half) or a non-empty list of incident ids")
    if pipeline.get("profile", "accuracy") not in ("accuracy", "end-to-end"):
        problems.append("pipeline.profile must be accuracy or end-to-end")
    if not (config["ground_truth"] or {}).get("dir"):
        problems.append("ground_truth.dir must name a frozen ground-truth directory")
    if config["split"] == "test":
        if config["final"] is not True:
            problems.append("the test split is only for the final, pre-registered run (final: true)")
        if not config["selection_record"] or not selection_record_exists(config["selection_record"], decisions_path):
            problems.append("a test run must name an existing .docs/decisions.md selection record (### heading)")
    elif config["final"]:
        problems.append("final runs are on the test split only")
    return problems


def videos_for(config: dict, split: dict) -> list[str]:
    """The split half, or the config's subset of it (a pilot); a video outside the half is refused."""
    half = list(split[config["split"]])
    if config.get("videos") is None:
        return half
    outside = sorted(set(config["videos"]) - set(half))
    if outside:
        raise ExperimentRefused(f"videos {outside} are not in the {config['split']} half of the split")
    return [v for v in half if v in set(config["videos"])]


def planned_calls(config: dict, split: dict) -> int:
    return len(videos_for(config, split)) * config["repeats"]


def completed_runs(experiment_id: str, root: Path = RESULTS_ROOT) -> list[Path]:
    directory = root / experiment_id
    return sorted(p.parent for p in directory.glob("*/results.json")
                  if json.loads(p.read_text()).get("complete")) if directory.exists() else []


def preflight(config: dict, split: dict, *, registry: dict | None = None, results_root: Path = RESULTS_ROOT,
              decisions_path: Path = DECISIONS_PATH) -> dict:
    """Every guard that needs no network. Returns the plan or raises ``ExperimentRefused``."""
    problems = config_problems(config, registry=registry, decisions_path=decisions_path)
    if problems:
        raise ExperimentRefused("; ".join(problems))
    if config["frozen_baseline"] and completed_runs(config["experiment_id"], results_root):
        raise ExperimentRefused(f"{config['experiment_id']} is a frozen baseline with a completed run; re-score its "
                                "saved outputs (--rescore) instead of running it again")
    calls = planned_calls(config, split)
    if calls > config["budget"]["max_p1_calls"]:
        raise ExperimentRefused(f"{calls} planned P1 calls exceed budget.max_p1_calls {config['budget']['max_p1_calls']}")
    item = prompt_registry.entry(config["prompt_id"], registry)
    return {"experiment_id": config["experiment_id"], "arm": config["arm"], "model": config["model"],
            "prompt_id": item["id"], "prompt_sha256": item["sha256"], "split": config["split"],
            "videos": len(videos_for(config, split)), "repeats": config["repeats"], "planned_p1_calls": calls,
            "budget_max_p1_calls": config["budget"]["max_p1_calls"]}


# --- transports -----------------------------------------------------------------------------------

@dataclass
class VSSResponse:
    status_code: int | None
    body: object
    elapsed_s: float
    error: str | None = None
    timed_out: bool = False


def post_json(url: str, payload: dict, *, timeout: float) -> VSSResponse:
    import requests

    started = time.perf_counter()
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return VSSResponse(None, None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}",
                           timed_out=isinstance(exc, requests.Timeout))
    try:
        body = response.json()
    except ValueError:
        body = response.text[:1000]
    return VSSResponse(response.status_code, body, time.perf_counter() - started)


def vss_chat_result(response: VSSResponse, *, prompt_id: str, prompt_sha256: str, started_at: str, finished_at: str):
    """The agent's answer as a ``ChatResult`` (the eval.md §4 Track X rules).

    A 200, or a 422 whose ``detail`` carries a string ``raw_output``, is a model output and
    goes through ``evaluate_policy`` like the direct arm; the agent's own acceptance decision
    never replaces core-scored-v1. Everything else is a request failure.
    """
    from eval_vlm_client import ChatResult

    timing = {"elapsed_s": response.elapsed_s, "started_at": started_at, "finished_at": finished_at}
    if response.status_code is None:
        return ChatResult(ok=False, error=response.error, failure_kind="timeout" if response.timed_out
                          else "transport_error", **timing)
    body = response.body if isinstance(response.body, dict) else {}
    if response.status_code == 200:
        payload = body
    elif response.status_code == 422 and isinstance(body.get("detail"), dict) \
            and isinstance(body["detail"].get("raw_output"), str):
        payload = body["detail"]
    else:
        kind = {429: "rate_limited", 504: "timeout"}.get(response.status_code, "http_error")
        return ChatResult(ok=False, status_code=response.status_code, error=json.dumps(response.body)[:1000],
                          failure_kind=kind, raw=body, **timing)
    if payload.get("contract_version") != contract.contract_version():
        return ChatResult(ok=False, status_code=response.status_code, failure_kind="http_error", raw=body,
                          error=f"agent contract_version {payload.get('contract_version')!r} is not "
                                f"{contract.contract_version()!r}", **timing)
    used = payload.get("experiment") or {}
    if prompt_id != prompt_registry.BASE_ID and (used.get("prompt_id"), used.get("prompt_sha256")) != \
            (prompt_id, prompt_sha256):
        return ChatResult(ok=False, status_code=response.status_code, failure_kind="http_error", raw=body,
                          error=f"the agent did not confirm experiment prompt {prompt_id} ({prompt_sha256[:12]}); "
                                f"it reported {used or 'none'}", **timing)
    raw = {**body, "usage": payload.get("usage") or {}, "agent": {
        "status_code": response.status_code, "p1_elapsed_ms": payload.get("p1_elapsed_ms"),
        "end_to_end_s": response.elapsed_s, "experiment": used, "model": payload.get("model")}}
    return ChatResult(ok=True, content=payload.get("raw_output"), finish_reason=payload.get("finish_reason"),
                      status_code=response.status_code, raw=raw, **timing)


def direct_call(prompt_text: str, *, pacer=None) -> Callable:
    """The direct-VLM arm: ``eval_vlm_client`` with the registry prompt."""
    from eval_vlm_client import analyze_video_with_p1, rate_limited

    def call(model: str, video_url: str):
        return rate_limited(lambda: analyze_video_with_p1(model, video_url, prompt_text=prompt_text), pacer=pacer)

    return call


def vss_call(config: dict, item: dict, *, incident_id: str, run_id: str, duration: float | None, pacer=None,
             post: Callable = post_json, timeout: float | None = None) -> Callable:
    """The VSS arm: the agent's ``/analyze`` with P1 only, cropping off, the experiment prompt by id."""
    from eval_vlm_client import P1_TIMEOUT_SECONDS, _utc_now, rate_limited

    base = config["pipeline"]["agent_base_url"].rstrip("/")

    def call(model: str, video_url: str):
        payload = {"video_url": video_url, "model": model, "model_run_id": run_id, "skip_rp1": True,
                   "skip_crops": config["pipeline"]["skip_crops"]}
        if duration:
            payload["video_duration_seconds"] = duration
        if item["id"] != prompt_registry.BASE_ID:
            payload["experiment_prompt_id"] = item["id"]

        def once():
            started_at = _utc_now()
            response = post(f"{base}/api/v1/incidents/{incident_id}/analyze", payload,
                            timeout=timeout or P1_TIMEOUT_SECONDS + 60)
            return vss_chat_result(response, prompt_id=item["id"], prompt_sha256=item["sha256"], started_at=started_at,
                                   finished_at=_utc_now())

        return rate_limited(once, pacer=pacer)

    return call


# --- running ------------------------------------------------------------------------------------

def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=EVAL_DIR,
                              check=False).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def run_id_for(config: dict, repeat: int) -> str:
    digest = hashlib.sha256(f"{config['experiment_id']}:{repeat}".encode()).hexdigest()[:12]
    run_id = f"X{'d' if config['arm'] == 'direct-vlm' else 'v'}{repeat}-{digest}"[:20]
    assert RUN_ID_PATTERN.match(run_id)
    return run_id


def metadata(config: dict, plan: dict, gt_index: dict, *, registry: dict | None = None) -> dict:
    """Everything §F.4 requires each configuration to record."""
    item = prompt_registry.entry(config["prompt_id"], registry)
    return {
        "experiment_id": config["experiment_id"],
        "config": config,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "arm": config["arm"],
        "model": config["model"],
        "prompt": {**item, "lineage": prompt_registry.lineage(item["id"], registry)},
        "contract_version": contract.contract_version(),
        "schema_sha256": hashlib.sha256(contract.SCHEMA_PATH.read_bytes()).hexdigest(),
        "inference": contract.load_inference().get("p1"),
        "pipeline": config["pipeline"],
        "ground_truth": {"version": gt_index.get("version"), "status": gt_index.get("status"),
                         "dir": config["ground_truth"]["dir"],
                         "records_sha256": (gt_index.get("manifest") or {}).get("records_sha256")},
        "reportable": gt_index.get("status") == "frozen",
        "split": {"version": (gt_index.get("split") or {}).get("version"), "half": config["split"]},
        "methodology": methodology.record(),
        "harness_git_sha": git_sha(),
        "plan": plan,
    }


def run_experiment(config: dict, *, split: dict, gt_index: dict, store, video_source: Callable,
                   call_factory: Callable, run_one: Callable, confirm_paid: bool, results_root: Path = RESULTS_ROOT,
                   registry: dict | None = None, decisions_path: Path = DECISIONS_PATH, now: datetime | None = None,
                   log: Callable = print) -> dict:
    """Run one configuration. ``video_source(incident_id) -> (video_url, metadata)``;
    ``call_factory(incident_id, run_id, duration) -> p1_call``; ``run_one`` is ``eval_run.run_one_video``."""
    plan = preflight(config, split, registry=registry, results_root=results_root, decisions_path=decisions_path)
    if not confirm_paid:
        return {"dry_run": True, "plan": plan}
    if gt_index.get("status") != "frozen" and not (config["ground_truth"] or {}).get("allow_candidate"):
        raise ExperimentRefused("ground truth is not frozen; only a plumbing run may set ground_truth.allow_candidate")
    started = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    out_dir = results_root / config["experiment_id"] / started
    if out_dir.exists():
        raise ExperimentRefused(f"{out_dir} exists; results are immutable")
    out_dir.mkdir(parents=True)
    record = {**metadata(config, plan, gt_index, registry=registry), "started_at": started, "complete": False,
              "videos": []}
    for repeat in range(1, config["repeats"] + 1):
        run_id = run_id_for(config, repeat)
        store.insert_model_run(run_id, model_name=config["model"], prompt_version=contract.contract_version())
        for incident_id in videos_for(config, split):
            entry = gt_index["by_incident_id"][incident_id]
            video_url, video = video_source(incident_id)
            seen: list = []
            p1_call = call_factory(incident_id, run_id, video.get("duration_seconds"))

            def recording_call(model: str, url: str, _call=p1_call, _seen=seen):
                outcome = _call(model, url)
                _seen.append(outcome)
                return outcome

            result = run_one(
                store, model=config["model"], category=entry["category"], filename=entry["filename"],
                incident_id=incident_id, r2_object_key=video.get("r2_object_key"), video_url=video_url,
                gt_p1_shaped=entry["p1_shaped"], model_run_id=run_id, split_manifest_ref=str(SPLIT_PATH.name),
                video_duration_seconds=video.get("duration_seconds"), video_size_bytes=video.get("size_bytes"),
                p1_call=recording_call)
            # The agent's own report of the call (P1-only time, end-to-end time, the prompt it used).
            result["transport"] = (seen[-1].result.raw or {}).get("agent") if seen else None
            result["repeat"] = repeat
            result["arm"] = config["arm"]
            result["prompt_id"] = config["prompt_id"]
            record["videos"].append(result)
            log(f"  {config['experiment_id']} r{repeat} {incident_id}: {result['outcome']}")
    record["complete"] = True
    record["finished_at"] = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    record["reliability"] = extraction_stats.reliability(record["videos"])
    content = (json.dumps(record, indent=2, default=str) + "\n").encode()
    (out_dir / "results.json").write_bytes(content)
    (out_dir / "prompt.txt").write_text(prompt_registry.prompt_text(config["prompt_id"], registry=registry))
    # Written once; experiment_verify.py checks the results were not edited afterwards.
    (out_dir / "results.sha256").write_text(hashlib.sha256(content).hexdigest() + "  results.json\n")
    return {"dry_run": False, "plan": plan, "results": str(out_dir / "results.json"), "record": record}


# --- comparisons ----------------------------------------------------------------------------------

def per_video_means(videos: list[dict], field: str) -> dict[str, float | None]:
    """Mean field value per video across repeats (unscored values left out; ``None`` if none count)."""
    values: dict[str, list[float]] = {}
    for video in videos:
        value = extraction_stats.field_value(video, field)
        values.setdefault(video["incident_id"], [])
        if value is not None:
            values[video["incident_id"]].append(value)
    return {k: (sum(v) / len(v) if v else None) for k, v in values.items()}


def paired_comparison(videos_a: list[dict], videos_b: list[dict], field: str) -> dict:
    """B - A per video (repeats averaged first), with the methodology's paired bootstrap interval."""
    a, b = per_video_means(videos_a, field), per_video_means(videos_b, field)
    shared = sorted(set(a) & set(b))
    differences = [b[i] - a[i] for i in shared if a[i] is not None and b[i] is not None]
    interval = extraction_stats._interval(differences)
    return {"field": field, "n_pairs": len(differences), "excluded": len(set(a) | set(b)) - len(differences),
            "mean_difference": round(sum(differences) / len(differences), 4) if differences else None,
            "ci95": interval}


# The four mandatory Stage 3 comparisons (plan §F.2): (name, minuend, subtrahend, what it measures).
COMPARISONS = (
    ("C2-C1", "C2", "C1", "pipeline effect at the baseline prompt (parity / reliability)"),
    ("C3-C2", "C3", "C2", "prompt-engineering effect inside VSS (RQ1)"),
    ("C4-C1", "C4", "C1", "prompt-engineering effect without VSS (transfer)"),
    ("C3-C4", "C3", "C4", "pipeline effect at the optimised prompt (RQ2, attributed)"),
)


def configuration_problems(records: dict[str, dict]) -> list[str]:
    """C1-C4 must share everything not under test (plan §F.4)."""
    problems = []
    expected = {"C1": ("direct-vlm", "base"), "C2": ("vss", "base"), "C3": ("vss", "selected"), "C4": ("direct-vlm", "selected")}
    for name, (arm, prompt) in expected.items():
        if name not in records:
            problems.append(f"{name} is missing")
            continue
        if records[name]["arm"] != arm:
            problems.append(f"{name} must be the {arm} arm")
        is_base = records[name]["prompt"]["id"] == prompt_registry.BASE_ID
        if is_base != (prompt == "base"):
            problems.append(f"{name} must use {'the baseline' if prompt == 'base' else 'the selected'} prompt")
    present = [records[n] for n in expected if n in records]
    for key, label in ((lambda r: r["model"], "model"), (lambda r: r["ground_truth"]["records_sha256"], "ground truth"),
                       (lambda r: r["split"]["half"], "split"), (lambda r: r["methodology"]["methodology_version"],
                                                                 "methodology"),
                       (lambda r: sorted({v["incident_id"] for v in r["videos"]}), "video set")):
        if len({json.dumps(key(r), default=str) for r in present}) > 1:
            problems.append(f"C1-C4 differ in {label}")
    if "C3" in records and "C4" in records and records["C3"]["prompt"]["sha256"] != records["C4"]["prompt"]["sha256"]:
        problems.append("C3 and C4 must use the byte-identical selected prompt")
    return problems


def four_way(records: dict[str, dict], fields=extraction_stats.INCIDENT_FIELDS) -> dict:
    """The four paired comparisons per field from saved outputs, plus C3-C1 decomposed."""
    out = {"problems": configuration_problems(records), "comparisons": {}}
    for name, minuend, subtrahend, meaning in COMPARISONS:
        if minuend in records and subtrahend in records:
            out["comparisons"][name] = {"meaning": meaning, "fields": {
                field: paired_comparison(records[subtrahend]["videos"], records[minuend]["videos"], field)
                for field in fields}}
    if all(k in records for k in ("C1", "C3", "C4")):
        out["comparisons"]["C3-C1"] = {"meaning": "best VSS vs fixed direct baseline = (C3-C4) + (C4-C1); never an "
                                                  "architecture claim", "fields": {
            field: paired_comparison(records["C1"]["videos"], records["C3"]["videos"], field) for field in fields}}
    return out
