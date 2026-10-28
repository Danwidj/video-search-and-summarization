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
import random
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
               "budget", "pipeline", "frozen_baseline", "final", "selection_record", "baseline_ref", "videos",
               "purpose", "scoring"}
SCORING = ("full", "incident_only")
PURPOSES = ("experiment", "pilot")
BUDGET_KEYS = ("max_p1_calls", "max_p1_tokens", "max_judge_calls")
PRICING_PATH = EVAL_DIR / "experiments" / "pricing.json"
JUDGE_CAPS_PATH = EVAL_DIR / "experiments" / "judge-caps.json"
# D10: deterministic randomisation of the video order per repeat.
ORDER_SEED = 20261027
# D11: the most one P1 attempt can use, which every cap check leaves room for: the largest 2026-10-02 Cosmos 3
# Super prompt (17,970 tokens, rounded up to 18,616) plus the request's max_tokens (16,384). An attempt that
# reports no usage and was not rejected with 429 is counted at this ceiling (it may still have been billed).
P1_TOKENS_CEILING = 35000
# A judged field costs at most 1 attempt + 2 parse retries + the methodology's transient retries.
JUDGE_ATTEMPTS_PER_FIELD = 3 + methodology.JUDGE_TRANSIENT_RETRIES
P1_RATE_LIMIT_RETRIES = 2  # eval_vlm_client.P1_RATE_LIMIT_POLICY["max_rate_limit_retries"] (a test keeps them equal)
P1_TOKENS_PLANNING_MEAN = 9898
RATE_LIMIT_STOP_SHARE = 0.25
# eval_vlm_client.P1_RETRY_POLICIES ids (a test keeps them equal). A config without pipeline.retry_policy ran
# under retry-v1, as Stages 0 and 1 did.
RETRY_POLICIES = ("retry-v1", "retry-v2")
DEFAULT_RETRY_POLICY = "retry-v1"
RATE_LIMIT_MIN_ATTEMPTS = 8
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
    for key in BUDGET_KEYS:
        if not isinstance((config["budget"] or {}).get(key), int) or config["budget"][key] < 1:
            problems.append(f"budget.{key} must be a whole number >= 1 (hard cap)")
    if config["purpose"] not in PURPOSES:
        problems.append(f"purpose must be one of {PURPOSES}")
    if config["purpose"] == "pilot" and (config["split"] != "dev" or config["final"] or config["frozen_baseline"]):
        problems.append("a pilot runs on dev only and is never final or a frozen baseline")
    if config["scoring"] not in SCORING:
        problems.append(f"scoring must be one of {SCORING}")
    if config["purpose"] == "experiment" and config["scoring"] != "full":
        problems.append("an experiment is scored in full (D9 needs the item F1 scores); incident_only is for pilots")
    pipeline = config["pipeline"] or {}
    if pipeline.get("skip_rp1") is not True:
        problems.append("pipeline.skip_rp1 must be true: RP1 is not part of an extraction experiment")
    if pipeline.get("profile", "accuracy") == "accuracy" and pipeline.get("skip_crops") is not True:
        problems.append("pipeline.skip_crops must be true for an accuracy run (cropping is the end-to-end profile only)")
    if pipeline.get("retry_policy", DEFAULT_RETRY_POLICY) not in RETRY_POLICIES:
        problems.append(f"pipeline.retry_policy must be one of {RETRY_POLICIES}")
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
              decisions_path: Path = DECISIONS_PATH, planned: int | None = None) -> dict:
    """Every guard that needs no network. Returns the plan or raises ``ExperimentRefused``.

    ``planned`` overrides the planned call count (a recovery runs only listed video-runs).
    """
    problems = config_problems(config, registry=registry, decisions_path=decisions_path)
    if problems:
        raise ExperimentRefused("; ".join(problems))
    if config["frozen_baseline"] and completed_runs(config["experiment_id"], results_root):
        raise ExperimentRefused(f"{config['experiment_id']} is a frozen baseline with a completed run; re-score its "
                                "saved outputs (--rescore) instead of running it again")
    calls = planned_calls(config, split) if planned is None else planned
    if calls > config["budget"]["max_p1_calls"]:
        raise ExperimentRefused(f"{calls} planned P1 calls exceed budget.max_p1_calls {config['budget']['max_p1_calls']}")
    if calls * P1_TOKENS_PLANNING_MEAN > config["budget"]["max_p1_tokens"]:
        raise ExperimentRefused(f"{calls} planned P1 calls need about {calls * P1_TOKENS_PLANNING_MEAN} tokens, more "
                                f"than budget.max_p1_tokens {config['budget']['max_p1_tokens']}")
    item = prompt_registry.entry(config["prompt_id"], registry)
    return {"experiment_id": config["experiment_id"], "arm": config["arm"], "model": config["model"],
            "prompt_id": item["id"], "prompt_sha256": item["sha256"], "split": config["split"],
            "videos": len(videos_for(config, split)), "repeats": config["repeats"], "planned_p1_calls": calls,
            "budget_max_p1_calls": config["budget"]["max_p1_calls"], "budget": dict(config["budget"]),
            "purpose": config["purpose"]}


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


# Gateway or upstream timeouts: 504 (agent or proxy), 522 and 524 (Cloudflare: the origin took longer than
# about 100 s). They are timeouts, not HTTP errors: no model output, counted as a miss end to end.
GATEWAY_TIMEOUT_STATUS = (504, 522, 524)


def _upstream_status(body) -> int | None:
    """The upstream status the agent wraps in a 500 ``P1 call returned HTTP 524: ...`` (or 429)."""
    detail = body.get("detail") if isinstance(body, dict) else body
    match = re.search(r"P1 call returned HTTP (\d{3})\b", str(detail or ""))
    return int(match.group(1)) if match else None


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
        status = _upstream_status(response.body) or response.status_code
        kind = {429: "rate_limited"}.get(status) or ("timeout" if status in GATEWAY_TIMEOUT_STATUS
                                                     else "http_error")
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


def retry_policy(config: dict) -> str:
    return (config.get("pipeline") or {}).get("retry_policy", DEFAULT_RETRY_POLICY)


def direct_call(prompt_text: str, *, pacer=None, max_retries: int | None = None,
                policy: str = DEFAULT_RETRY_POLICY) -> Callable:
    """The direct-VLM arm: ``eval_vlm_client`` with the registry prompt."""
    from eval_vlm_client import analyze_video_with_p1, rate_limited

    def call(model: str, video_url: str):
        return rate_limited(lambda: analyze_video_with_p1(model, video_url, prompt_text=prompt_text), pacer=pacer,
                            max_retries=max_retries, policy=policy)

    return call


def vss_call(config: dict, item: dict, *, incident_id: str, run_id: str, duration: float | None, pacer=None,
             post: Callable = post_json, timeout: float | None = None, max_retries: int | None = None) -> Callable:
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

        return rate_limited(once, pacer=pacer, max_retries=max_retries, policy=retry_policy(config))

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
        # A pilot is never reportable: it validates infrastructure, reliability, latency and cost only.
        "reportable": gt_index.get("status") == "frozen" and config["purpose"] == "experiment",
        "purpose": config["purpose"],
        "split": {"version": (gt_index.get("split") or {}).get("version"), "half": config["split"]},
        "methodology": methodology.record(),
        "harness_git_sha": git_sha(),
        "plan": plan,
    }


def load_pricing(path: Path | None = None) -> dict:
    return json.loads((path or PRICING_PATH).read_text())


def _rate(pricing: dict, model: str) -> float:
    rates = pricing["usd_per_million_tokens"]
    return float(rates.get(model, rates["default"]))


def call_usage(result: dict, pricing: dict, model: str) -> dict:
    """Requests, tokens and provisional cost of one video-run.

    ``p1_tokens_bound`` is the pessimistic count the caps use: measured usage, plus the per-attempt
    ceiling for every attempt that reported no usage and was not a 429 rejection. Judge tokens are
    measured from the endpoint's usage; the estimate is kept for runs scored before it was recorded.
    """
    raw = result.get("p1_raw") or {}
    usage = raw.get("usage") or {}
    p1_tokens = int(usage.get("total_tokens") or (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens")
                                                                                         or 0))
    attempts = (raw.get("rate_limit") or {}).get("attempts") or [{"ok": raw.get("ok"),
                                                                  "failure_kind": raw.get("failure_kind")}]
    unmetered = sum(1 for a in attempts if a.get("failure_kind") not in (None, "rate_limited", "not_sent"))
    if not p1_tokens and raw.get("ok"):
        unmetered += 1  # a successful attempt without a usage block
    judge_calls = int(result.get("judge_calls") or 0)
    judge_tokens = int(result.get("judge_tokens") or 0)
    judge_estimate = judge_calls * int(pricing["judge_tokens_per_call_estimate"])
    judge_priced = judge_tokens or judge_estimate
    cost = p1_tokens / 1e6 * _rate(pricing, model) + judge_priced / 1e6 * _rate(pricing, pricing["judge_model"])
    return {"p1_attempts": len(attempts), "p1_prompt_tokens": usage.get("prompt_tokens"),
            "p1_completion_tokens": usage.get("completion_tokens"), "p1_total_tokens": p1_tokens,
            "p1_tokens_bound": p1_tokens + unmetered * P1_TOKENS_CEILING, "judge_calls": judge_calls,
            "judge_tokens": judge_tokens, "judge_tokens_estimate": judge_estimate,
            "cost_usd_provisional": round(cost, 6)}


def judged_fields(gt_p1_shaped: dict, scoring: str) -> int:
    """Judged fields of one video: the incident description, plus (full) 1 per entity and 2 per instrument and asset."""
    fields = 1
    if scoring == "full":
        fields += len(gt_p1_shaped.get("entities") or []) + 2 * len(gt_p1_shaped.get("instruments") or []) \
            + 2 * len(gt_p1_shaped.get("assets") or [])
    return fields


def judge_cap_required(config: dict, split: dict, gt_index: dict) -> dict:
    """The judge-request cap a configuration needs so the full planned run can never hit it.

    ``required = repeats x sum over its videos of (judged fields x attempts per field)``: the same
    worst case the runner reserves before each video, summed over the plan. A video's judged fields
    are bounded by its ground truth (a match never exceeds the ground-truth items).
    """
    per_video = {v: judged_fields(gt_index["by_incident_id"][v]["p1_shaped"], config["scoring"])
                 for v in videos_for(config, split)}
    required = config["repeats"] * sum(per_video.values()) * JUDGE_ATTEMPTS_PER_FIELD
    return {"experiment_id": config["experiment_id"], "videos": len(per_video), "repeats": config["repeats"],
            "judged_fields": sum(per_video.values()), "attempts_per_field": JUDGE_ATTEMPTS_PER_FIELD,
            "required": required, "configured": config["budget"]["max_judge_calls"], "per_video": per_video}


def subset_judge_cap(config: dict, runs: set[tuple[int, str]], gt_index: dict) -> dict:
    """``judge_cap_required`` for listed ``(repeat, incident_id)`` video-runs only (a recovery)."""
    fields = sum(judged_fields(gt_index["by_incident_id"][v]["p1_shaped"], config["scoring"]) for _, v in runs)
    return {"experiment_id": config["experiment_id"], "videos": len({v for _, v in runs}), "repeats": None,
            "judged_fields": fields, "attempts_per_field": JUDGE_ATTEMPTS_PER_FIELD,
            "required": fields * JUDGE_ATTEMPTS_PER_FIELD, "configured": config["budget"]["max_judge_calls"]}


def worst_judge_attempts(gt_p1_shaped: dict, scoring: str) -> int:
    """The most judge requests one video can cause: judged fields x attempts per field.

    Judged fields: the incident description, plus (full scoring) one per ground-truth entity and two
    (name, description) per instrument and asset; a match never exceeds the ground-truth items.
    """
    return judged_fields(gt_p1_shaped, scoring) * JUDGE_ATTEMPTS_PER_FIELD


def schedule(configs: list[dict], videos: list[str], repeats: int, seed: int = ORDER_SEED) -> list[tuple]:
    """``(repeat, position, incident_id, config index)`` in run order (D10).

    Per repeat the videos are shuffled with ``random.Random(seed + repeat)``; at each video the
    configurations run interleaved, the first one rotating with the position, so no arm always
    runs first or in one block. Deterministic: the same inputs always give the same order.
    """
    order = []
    for repeat in range(1, repeats + 1):
        shuffled = sorted(videos)
        random.Random(seed + repeat).shuffle(shuffled)
        for position, incident_id in enumerate(shuffled):
            for k in range(len(configs)):
                order.append((repeat, position, incident_id, (position + k) % len(configs)))
    return order


def write_checkpoint(stage_dir: Path, *, order, done: int, records, run_ids, attempts: int, rate_limited: int) -> None:
    """The stage's progress after each video-run, replaced atomically (a crash never leaves half a file)."""
    tmp = stage_dir / "checkpoint.json.tmp"
    tmp.write_text(json.dumps({"order": [list(o) for o in order], "done": done, "records": records,
                               "run_ids": [[k, r, v] for (k, r), v in run_ids.items()], "attempts": attempts,
                               "rate_limited": rate_limited}, default=str))
    tmp.replace(stage_dir / "checkpoint.json")


def run_stage(configs: list[dict], *, split: dict, gt_index: dict, store, video_source: Callable,
              call_factory_for: Callable, run_one: Callable, confirm_paid: bool, results_root: Path = RESULTS_ROOT,
              registry: dict | None = None, decisions_path: Path = DECISIONS_PATH, now: datetime | None = None,
              log: Callable = print, pricing: dict | None = None, seed: int = ORDER_SEED,
              only: dict[str, set[tuple[int, str]]] | None = None, recovery: dict[str, dict] | None = None,
              resume: Path | None = None) -> dict:
    """Run configurations interleaved per video under hard caps; write one immutable result per configuration.

    ``call_factory_for(config) -> call_factory(incident_id, run_id, duration) -> p1_call``. Every
    configuration must cover the same videos with the same repeats. Before each call the
    configuration's caps are checked with room for a worst-case call; a cap, or rate limiting on
    more than a quarter of attempts, stops the whole stage. The partial results are then written
    with ``complete: false`` and the reason. Every call is appended to the stage's ``cost-log.jsonl``.

    ``only`` (recovery, ``experiment_recovery``) limits each configuration to the listed ``(repeat,
    incident_id)`` video-runs, still in the interleaved D10 order; ``recovery`` names, per configuration,
    the original result it recovers and the original video-run each recovered one replaces.

    After every video-run the stage writes ``checkpoint.json`` (the records so far, the run ids and the
    rate-limit counters). ``resume`` (that stage directory) continues an interrupted stage with the same
    configurations: the finished video-runs are kept, the rest run in the same D10 order, and the result
    is written once at the end, as for an uninterrupted stage (``resumed`` lists when it was resumed).
    """
    if only is not None and set(only) != {c["experiment_id"] for c in configs}:
        raise ExperimentRefused("a recovery lists the video-runs of every configuration in the stage")
    plans = [preflight(c, split, registry=registry, results_root=results_root, decisions_path=decisions_path,
                       planned=None if only is None else len(only[c["experiment_id"]])) for c in configs]
    if len({c["experiment_id"] for c in configs}) != len(configs):
        raise ExperimentRefused("a stage cannot run the same configuration twice")
    video_sets = {tuple(sorted(videos_for(c, split))) for c in configs}
    if only is not None:
        video_sets = {tuple(sorted(set().union(*video_sets)))}
    if len(video_sets) != 1 or len({c["repeats"] for c in configs}) != 1 or len({c["split"] for c in configs}) != 1:
        raise ExperimentRefused("configurations in one stage must share split half, videos and repeats")
    if not confirm_paid:
        return {"dry_run": True, "plans": plans, "plan": plans[0]}
    for config in configs:
        if gt_index.get("status") != "frozen" and not (config["ground_truth"] or {}).get("allow_candidate"):
            raise ExperimentRefused(f"{config['experiment_id']}: ground truth is not frozen; only a pilot or plumbing "
                                    "run may set ground_truth.allow_candidate")
    for config in configs:
        caps = judge_cap_required(config, split, gt_index) if only is None else \
            subset_judge_cap(config, only[config["experiment_id"]], gt_index)
        if caps["configured"] < caps["required"]:
            raise ExperimentRefused(
                f"{config['experiment_id']}: budget.max_judge_calls {caps['configured']} is below the "
                f"{caps['required']} the full plan can need ({caps['repeats']} repeats x {caps['judged_fields']} "
                f"judged fields x {caps['attempts_per_field']} attempts); re-derive it with 'eval_experiment.py caps'")
    pricing = pricing or load_pricing()
    stage_id = hashlib.sha256(",".join(c["experiment_id"] for c in configs).encode()).hexdigest()[:8]
    checkpoint = None
    if resume is not None:
        started, _, resumed_id = resume.name.partition("-")
        if resumed_id != stage_id or not (resume / "checkpoint.json").exists():
            raise ExperimentRefused(f"{resume} is not an interrupted stage of these configurations")
        checkpoint = json.loads((resume / "checkpoint.json").read_text())
    else:
        started = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    out_dirs = [results_root / c["experiment_id"] / started for c in configs]
    stage_dir = results_root / "stages" / f"{started}-{stage_id}"
    if checkpoint is None:
        for path in [*out_dirs, stage_dir]:
            if path.exists():
                raise ExperimentRefused(f"{path} exists; results are immutable")
        for path in [*out_dirs, stage_dir]:
            path.mkdir(parents=True)
    elif any((d / "results.json").exists() for d in out_dirs):
        raise ExperimentRefused("this stage already wrote its results; it cannot be resumed")
    order = schedule(configs, list(video_sets.pop()), configs[0]["repeats"], seed)
    if only is not None:
        order = [o for o in order if (o[0], o[2]) in only[configs[o[3]]["experiment_id"]]]
    (stage_dir / "schedule.json").write_text(json.dumps({
        "seed": seed, "configs": [c["experiment_id"] for c in configs], "pricing": pricing,
        "order": [{"repeat": r, "position": p, "incident_id": v, "config": configs[k]["experiment_id"]}
                  for r, p, v, k in order]}, indent=2) + "\n")
    records = [{**metadata(c, plan, gt_index, registry=registry), "started_at": started, "complete": False,
                "stopped": None, "videos": [], "schedule": {"seed": seed, "stage": started},
                "usage": {"p1_calls": 0, "p1_attempts": 0, "p1_tokens": 0, "p1_tokens_bound": 0, "judge_calls": 0,
                          "judge_tokens": 0, "judge_tokens_estimate": 0,
                          "cost_usd_provisional": 0.0, "pricing_provisional": pricing.get("provisional", True)}}
               for c, plan in zip(configs, plans, strict=True)]
    for config, record in zip(configs, records, strict=True):
        if recovery is not None:
            record.update(protocol="recovery-v1", recovers=recovery[config["experiment_id"]]["of"])
    factories = [call_factory_for(c) for c in configs]
    planned_runs = [planned_calls(c, split) if only is None else len(only[c["experiment_id"]]) for c in configs]
    run_ids: dict[tuple, str] = {}
    stopped = None
    attempts = rate_limited = done = 0
    if checkpoint is not None:
        if checkpoint["order"] != [list(o) for o in order]:
            raise ExperimentRefused("the checkpoint's order differs from this stage's order")
        records, done = checkpoint["records"], checkpoint["done"]
        attempts, rate_limited = checkpoint["attempts"], checkpoint["rate_limited"]
        run_ids = {(k, r): v for k, r, v in checkpoint["run_ids"]}
        for record in records:
            record.setdefault("resumed", []).append({"at": datetime.now(UTC).isoformat(timespec="seconds"),
                                                     "after_video_runs": done})
        for (k, _repeat), run_id in run_ids.items():  # a fresh store needs the model runs it already has
            store.insert_model_run(run_id, model_name=configs[k]["model"], prompt_version=contract.contract_version())
    with (stage_dir / "cost-log.jsonl").open("a") as cost_log:
        for index, (repeat, position, incident_id, k) in enumerate(order):
            if index < done:
                continue
            config, record = configs[k], records[k]
            budget, used = config["budget"], record["usage"]
            reason = None
            entry = gt_index["by_incident_id"][incident_id]
            # Retries draw on the same request cap: only attempts left over after one per remaining run.
            remaining_runs = planned_runs[k] - used["p1_calls"]
            spare = budget["max_p1_calls"] - used["p1_attempts"] - remaining_runs
            retries_allowed = max(0, min(P1_RATE_LIMIT_RETRIES, spare))
            judge_worst = worst_judge_attempts(entry["p1_shaped"], config["scoring"])
            if spare < 0 or used["p1_attempts"] + 1 > budget["max_p1_calls"]:
                reason = "max_p1_calls"
            elif used["p1_tokens_bound"] + P1_TOKENS_CEILING * (1 + retries_allowed) > budget["max_p1_tokens"]:
                reason = "max_p1_tokens (no room for this call's worst case)"
            elif used["judge_calls"] + judge_worst > budget["max_judge_calls"]:
                reason = f"max_judge_calls (this video could need {judge_worst} judge requests)"
            elif attempts >= RATE_LIMIT_MIN_ATTEMPTS and rate_limited / attempts > RATE_LIMIT_STOP_SHARE:
                reason = f"rate limited on {rate_limited}/{attempts} calls (> {RATE_LIMIT_STOP_SHARE:.0%})"
            if reason:
                stopped = {"config": config["experiment_id"], "reason": reason, "at": [repeat, position, incident_id]}
                log(f"  STOP: {config['experiment_id']} {reason}")
                break
            key = (k, repeat)
            if key not in run_ids:
                run_ids[key] = run_id_for(config, repeat)
                store.insert_model_run(run_ids[key], model_name=config["model"],
                                       prompt_version=contract.contract_version())
            video_url, video = video_source(incident_id)
            seen: list = []
            p1_call = factories[k](incident_id, run_ids[key], video.get("duration_seconds"), max_retries=retries_allowed)

            def recording_call(model: str, url: str, _call=p1_call, _seen=seen):
                outcome = _call(model, url)
                _seen.append(outcome)
                return outcome

            result = run_one(
                store, model=config["model"], category=entry["category"], filename=entry["filename"],
                incident_id=incident_id, r2_object_key=video.get("r2_object_key"), video_url=video_url,
                gt_p1_shaped=entry["p1_shaped"], model_run_id=run_ids[key], split_manifest_ref=str(SPLIT_PATH.name),
                video_duration_seconds=video.get("duration_seconds"), video_size_bytes=video.get("size_bytes"),
                p1_call=recording_call, incident_only=config["scoring"] == "incident_only")
            # The agent's own report of the call (P1-only time, end-to-end time, the prompt it used).
            result["transport"] = (seen[-1].result.raw or {}).get("agent") if seen else None
            result.update(repeat=repeat, position=position, arm=config["arm"], prompt_id=config["prompt_id"])
            if recovery is not None:
                result["recovers"] = recovery[config["experiment_id"]]["links"][(repeat, incident_id)]
            usage = call_usage(result, pricing, config["model"])
            result["usage"] = usage
            record["videos"].append(result)
            used["p1_calls"] += 1
            used["p1_attempts"] += usage["p1_attempts"]
            used["p1_tokens"] += usage["p1_total_tokens"]
            used["p1_tokens_bound"] += usage["p1_tokens_bound"]
            used["judge_tokens"] += usage["judge_tokens"]
            used["judge_calls"] += usage["judge_calls"]
            used["judge_tokens_estimate"] += usage["judge_tokens_estimate"]
            used["cost_usd_provisional"] = round(used["cost_usd_provisional"] + usage["cost_usd_provisional"], 6)
            outcome_attempts = (result.get("p1_raw") or {}).get("rate_limit") or {}
            attempts += int(outcome_attempts.get("attempt_count") or 1)
            rate_limited += len(outcome_attempts.get("rate_limit_rejections") or [])
            cost_log.write(json.dumps({"time": datetime.now(UTC).isoformat(timespec="seconds"),
                                       "config": config["experiment_id"], "incident_id": incident_id,
                                       "repeat": repeat, "position": position, "outcome": result["outcome"], **usage,
                                       "config_cumulative": dict(used)}) + "\n")
            cost_log.flush()
            write_checkpoint(stage_dir, order=order, done=index + 1, records=records, run_ids=run_ids,
                             attempts=attempts, rate_limited=rate_limited)
            log(f"  {config['experiment_id']} r{repeat} {incident_id}: {result['outcome']} "
                f"tokens={usage['p1_total_tokens']} cost≈${used['cost_usd_provisional']:.4f}")
    finished = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    outputs = []
    for config, record, out_dir in zip(configs, records, out_dirs, strict=True):
        record["complete"] = stopped is None
        record["stopped"] = stopped
        record["finished_at"] = finished
        record["reliability"] = extraction_stats.reliability(record["videos"])
        content = (json.dumps(record, indent=2, default=str) + "\n").encode()
        (out_dir / "results.json").write_bytes(content)
        (out_dir / "prompt.txt").write_text(prompt_registry.prompt_text(config["prompt_id"], registry=registry))
        # Written once; experiment_report.verify checks the results were not edited afterwards.
        (out_dir / "results.sha256").write_text(hashlib.sha256(content).hexdigest() + "  results.json\n")
        outputs.append(str(out_dir / "results.json"))
    return {"dry_run": False, "plans": plans, "plan": plans[0], "results_files": outputs, "records": records,
            "stopped": stopped, "stage_dir": str(stage_dir)}


def run_experiment(config: dict, *, call_factory: Callable, **kwargs) -> dict:
    """One configuration as a stage of one (``run_stage``).

    ``call_factory(incident_id, run_id, duration, *, max_retries)``; ``max_retries`` is the share of the
    request cap this call may spend on 429 retries."""
    out = run_stage([config], call_factory_for=lambda _config: call_factory, **kwargs)
    if not out["dry_run"]:
        out["results"], out["record"] = out["results_files"][0], out["records"][0]
    return out


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
