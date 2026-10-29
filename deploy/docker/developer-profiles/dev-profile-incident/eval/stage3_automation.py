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

"""Stage 3 automation: progress log, resumable supervisor, recovery-v1, reports and the integrity audit.

``eval_stage3.py supervise`` is the single resumable launch command. It never resets the stage or starts a
second complete run:

- **Before each session:** the full preflight (manifest, hashes, ground truth, caps, request parity), host
  power and DNS. Any problem stops it.
- **Each session:** ``eval_experiment.py run <C1-C4> --confirm-paid --session-hours 4 [--resume <stage>]``
  under ``experiments/keep-awake.sh``. The runner checkpoints after every video-run, so a resume never
  repeats one.
- **Between sessions:**
  - a session-limit pause resumes at once;
  - an outage or rate-limit pause waits, then resumes, a bounded number of times;
  - a cap stop, a refusal, manifest drift or checkpoint corruption stops for the owner.
- **Progress:** every minute, ``<stage>/progress.json`` (and one line in ``progress.jsonl``) record:
  - runs done and remaining;
  - original and retry attempts;
  - valid and invalid outputs, and infrastructure failures;
  - tokens and judge calls against the caps;
  - elapsed time and the estimated time left;
  - checkpoint and manifest integrity.
- **After the 220 runs:**
  - ``verify``;
  - recovery-v1 of eligible infrastructure failures only (dry run, then paid, within its caps);
  - merged views (``recovered: 0`` where nothing was eligible);
  - the reports for both views;
  - the integrity audit.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import experiment_recovery as rec
import experiment_report
import experiment_runner as er
import extraction_stats
import methodology
import stage3

EVAL_DIR = stage3.EVAL_DIR
ENV_FILE = EVAL_DIR.parent / ".env.local"
REPORTS_DIR = EVAL_DIR / "eval_data" / "results" / "reports" / "stage3"
EMBEDDER_HEALTH = "http://127.0.0.1:8811/health"
AGENT_HEALTH = "http://127.0.0.1:8765/health"
SESSION_HOURS = 4
MAX_SESSIONS = 6
OUTAGE_RESUMES = 2
OUTAGE_WAIT_S = 900
CRASH_RESUMES = 2
PROGRESS_EVERY_S = 60


def log(message: str) -> None:
    print(f"[stage3 {datetime.now(UTC).isoformat(timespec='seconds')}] {message}", flush=True)


def stage_id(configs: dict[str, dict]) -> str:
    return hashlib.sha256(",".join(configs[n]["experiment_id"] for n in stage3.CONFIGS).encode()).hexdigest()[:8]


def find_stage(configs: dict[str, dict], results_root: Path = er.RESULTS_ROOT) -> list[Path]:
    return sorted((results_root / "stages").glob(f"*-{stage_id(configs)}"))


def stage_results(stage_dir: Path, configs: dict[str, dict], results_root: Path = er.RESULTS_ROOT) -> dict[str, Path]:
    started = stage_dir.name.split("-")[0]
    return {n: results_root / configs[n]["experiment_id"] / started / "results.json" for n in stage3.CONFIGS}


# --- progress -------------------------------------------------------------------------------------

def _cost_log(stage_dir: Path) -> list[dict]:
    path = stage_dir / "cost-log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def checkpoint_problems(stage_dir: Path) -> list[str]:
    """Corruption: the checkpoint must match the schedule, count its runs exactly and repeat none."""
    problems = []
    schedule = json.loads((stage_dir / "schedule.json").read_text())
    names = schedule["configs"]
    expected = [[o["repeat"], o["position"], o["incident_id"], names.index(o["config"])] for o in schedule["order"]]
    if not (stage_dir / "checkpoint.json").exists():
        return problems
    checkpoint = json.loads((stage_dir / "checkpoint.json").read_text())
    if checkpoint["order"] != expected:
        problems.append("the checkpoint's order differs from schedule.json")
    videos = [(r["experiment_id"], v["repeat"], v["incident_id"]) for r in checkpoint["records"] for v in r["videos"]]
    if len(videos) != checkpoint["done"]:
        problems.append(f"the checkpoint holds {len(videos)} video-runs but says {checkpoint['done']} are done")
    if len(set(videos)) != len(videos):
        problems.append("a video-run appears twice in the checkpoint")
    done = {(names[k], r, v) for r, _p, v, k in expected[:checkpoint["done"]]}
    if set(videos) != done:
        problems.append("the checkpoint's video-runs are not the first `done` entries of the schedule")
    return problems


def progress(stage_dir: Path, configs: dict[str, dict], *, results_root: Path = er.RESULTS_ROOT) -> dict:
    """The machine-readable state of the stage, from its checkpoint (or results) and cost log."""
    split = json.loads(er.SPLIT_PATH.read_text())
    results = stage_results(stage_dir, configs, results_root)
    complete = all(p.exists() for p in results.values())
    if complete:
        records = {n: json.loads(p.read_text()) for n, p in results.items()}
    else:
        checkpoint = json.loads((stage_dir / "checkpoint.json").read_text()) \
            if (stage_dir / "checkpoint.json").exists() else {"records": []}
        by_id = {r["experiment_id"]: r for r in checkpoint["records"]}
        records = {n: by_id.get(configs[n]["experiment_id"], {"videos": [], "usage": {}}) for n in stage3.CONFIGS}
    cost = _cost_log(stage_dir)
    per = {}
    for name, record in records.items():
        config, usage = configs[name], record.get("usage") or {}
        rel = extraction_stats.reliability(record["videos"]) if record["videos"] else None
        classes = {}
        for video in record["videos"]:
            cls = rec.failure_class(video)
            if cls:
                classes[cls] = classes.get(cls, 0) + 1
        planned = er.planned_calls(config, split)
        per[name] = {"experiment_id": config["experiment_id"], "done": len(record["videos"]),
                     "remaining": planned - len(record["videos"]),
                     "p1_attempts": usage.get("p1_attempts", 0),
                     "retry_attempts": usage.get("p1_attempts", 0) - usage.get("p1_calls", 0),
                     "outcomes": rel["outcomes"] if rel else {},
                     "valid_outputs": (rel["attempted"] - rel["no_model_output"] - rel["invalid_model_output"])
                     if rel else 0,
                     "invalid_model_outputs": rel["invalid_model_output"] if rel else 0,
                     "infrastructure_failures": classes,
                     "p1_tokens": usage.get("p1_tokens", 0), "p1_tokens_reserved": usage.get("p1_tokens_bound", 0),
                     "judge_calls": usage.get("judge_calls", 0), "judge_tokens": usage.get("judge_tokens", 0),
                     "caps": config["budget"]}
    done = sum(r["done"] for r in per.values())
    total = sum(er.planned_calls(c, split) for c in configs.values())
    times = [datetime.fromisoformat(c["time"]) for c in cost]
    gaps = [(b - a).total_seconds() for a, b in itertools.pairwise(times)]
    active = sum(g for g in gaps if g < 600)
    rate = len([g for g in gaps if g < 600]) / active if active else None
    committed = json.loads(stage3.MANIFEST_PATH.read_text())
    integrity = {"checkpoint": checkpoint_problems(stage_dir),
                 "manifest": stage3.manifest_problems(committed, stage3.build_manifest(configs, split)),
                 "cost_log_lines": len(cost), "cost_log_lines_beyond_checkpoint": max(0, len(cost) - done)}
    return {"at": datetime.now(UTC).isoformat(timespec="seconds"), "stage": str(stage_dir), "complete": complete,
            "scheduled": total, "done": done, "remaining": total - done, "configs": per,
            "totals": {k: sum(r[k] for r in per.values()) for k in
                       ("p1_attempts", "retry_attempts", "valid_outputs", "invalid_model_outputs", "p1_tokens",
                        "judge_calls", "judge_tokens")},
            "elapsed": {"first_run": cost[0]["time"] if cost else None, "last_run": cost[-1]["time"] if cost else None,
                        "active_hours": round(active / 3600, 2),
                        "runs_per_hour": round(rate * 3600, 1) if rate else None,
                        "estimated_remaining_hours": round((total - done) / rate / 3600, 2) if rate else None},
            "integrity": integrity,
            "integrity_ok": not integrity["checkpoint"] and not integrity["manifest"]}


def write_progress(stage_dir: Path, configs: dict[str, dict]) -> dict:
    state = progress(stage_dir, configs)
    tmp = stage_dir / "progress.json.tmp"
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(stage_dir / "progress.json")
    with (stage_dir / "progress.jsonl").open("a") as out:
        out.write(json.dumps({k: state[k] for k in ("at", "done", "remaining", "totals", "elapsed", "integrity_ok")})
                  + "\n")
    return state


# --- host and services ----------------------------------------------------------------------------

def runner_env() -> dict:
    """The runner's environment: gateway credentials from ../.env.local (never printed), the local embedder."""
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in ("VLM_GATEWAY_BASE_URL", "VLM_GATEWAY_API_KEY"):
            values[key.strip()] = value.strip().strip("'\"")
    env = {**os.environ, "INCIDENT_LLM_BASE_URL": values.get("VLM_GATEWAY_BASE_URL", ""),
           "INCIDENT_LLM_API_KEY": values.get("VLM_GATEWAY_API_KEY", ""),
           "INCIDENT_EMBEDDING_BASE_URL": methodology.EMBEDDING_BASE_URL}
    env.pop("INCIDENT_JUDGE_MODEL", None)
    return env


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def on_ac_power() -> bool | None:
    """True or False on WSL (Windows battery status 2 = on AC); None when it cannot be read."""
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_Battery).BatteryStatus"], check=False,
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    values = [v.strip() for v in out.stdout.splitlines() if v.strip()]
    return None if not values else all(v == "2" for v in values)


def dns_ok() -> bool:
    return subprocess.run(["getent", "hosts", "r2.cloudflarestorage.com"], capture_output=True, check=False).returncode == 0


class Services:
    """Starts the embedder and the local experiment agent when they are not already up; stops what it started."""

    def __init__(self, log_dir: Path):
        self.log_dir, self.started = log_dir, []

    def ensure(self) -> list[str]:
        problems = []
        for name, url, command, env in (
                ("embedder", EMBEDDER_HEALTH, [str(EVAL_DIR / ".venv" / "bin" / "python3"),
                                               "scripts/eval_embedding_server.py", "--port", "8811"], {}),
                ("agent", AGENT_HEALTH, ["experiments/agent/start-experiment-agent.sh"],
                 {"NAT_BIN": str(Path.home() / ".cache" / "vss-agent-venv" / "bin" / "nat")})):
            if healthy(url):
                continue
            out = (self.log_dir / f"{name}.log").open("a")
            self.started.append(subprocess.Popen(command, cwd=EVAL_DIR, env={**os.environ, **env}, stdout=out,
                                                 stderr=subprocess.STDOUT, start_new_session=True))
            log(f"started the {name}")
            for _ in range(60):
                if healthy(url):
                    break
                time.sleep(5)
            else:
                problems.append(f"the {name} did not become healthy at {url}")
        return problems

    def stop(self) -> None:
        for process in self.started:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.started = []


# --- supervisor -----------------------------------------------------------------------------------

def run_command(configs: dict[str, dict], resume: Path | None) -> list[str]:
    files = [f"experiments/configs/{configs[n]['experiment_id']}.json" for n in stage3.CONFIGS]
    command = ["experiments/keep-awake.sh", "--", str(EVAL_DIR / ".venv" / "bin" / "python"),
               "scripts/eval_experiment.py", "run", *files, "--confirm-paid", "--session-hours", str(SESSION_HOURS)]
    return command + (["--resume", str(resume)] if resume else [])


def _monitor(stage_holder: dict, configs: dict[str, dict], process: subprocess.Popen, stop: threading.Event,
             verdict: dict) -> None:
    while not stop.wait(PROGRESS_EVERY_S):
        if stage_holder.get("dir") is None:
            found = find_stage(configs)
            stage_holder["dir"] = found[0] if len(found) == 1 else None
        if stage_holder.get("dir") is None:
            continue
        try:
            state = write_progress(stage_holder["dir"], configs)
        except (OSError, ValueError, KeyError) as exc:  # a half-written file between runs: try again next minute
            log(f"progress not written: {exc}")
            continue
        if not state["integrity_ok"]:
            verdict["stop"] = f"integrity: {state['integrity']}"
            log(f"STOP: {verdict['stop']}; interrupting the runner")
            os.killpg(process.pid, signal.SIGINT)  # the runner's group: keep-awake's bash and the runner itself
            return


def supervise(*, wait=time.sleep) -> int:
    """Run (or resume) Stage 3 to the end, then finalise. Exit 0 when complete; 1 when stopped for the owner."""
    configs = stage3.load_configs()
    os.environ.setdefault("INCIDENT_EMBEDDING_BASE_URL", methodology.EMBEDDING_BASE_URL)  # the audit's re-matching
    log_dir = EVAL_DIR / "eval_data" / "results" / "stage3-supervisor"
    log_dir.mkdir(parents=True, exist_ok=True)
    services = Services(log_dir)
    sessions = outages = crashes = 0
    try:
        while True:
            stages = find_stage(configs)
            if len(stages) > 1:
                log(f"STOP: {len(stages)} Stage 3 stage directories exist; resolve this by hand: {stages}")
                return 1
            stage_dir = stages[0] if stages else None
            if stage_dir and all(p.exists() for p in stage_results(stage_dir, configs).values()):
                log(f"the 220 scheduled runs are recorded in {stage_dir}; finalising")
                return finalize(stage_dir, configs, services=services)
            if stage_dir is None and any(er.completed_runs(c["experiment_id"]) for c in configs.values()):
                log("STOP: a completed Stage 3 result exists without its stage directory")
                return 1
            pre = stage3.preflight_checks()
            if not pre["ok"]:
                log(f"STOP: preflight failed: { {k: v for k, v in pre['checks'].items() if v} }")
                return 1
            if stage_dir and (problems := checkpoint_problems(stage_dir)):
                log(f"STOP: checkpoint problems: {problems}")
                return 1
            if on_ac_power() is False:
                log("STOP: the laptop is on battery; reconnect AC (lid open) and rerun this command")
                return 1
            if not dns_ok():
                log("STOP: DNS for R2 does not resolve; rerun this command when the network is back")
                return 1
            if problems := services.ensure():
                log(f"STOP: {problems}")
                return 1
            if sessions >= MAX_SESSIONS:
                log(f"STOP: {MAX_SESSIONS} sessions without finishing; rerun this command to continue")
                return 1
            sessions += 1
            log(f"session {sessions}: {'resume ' + str(stage_dir) if stage_dir else 'new stage'}")
            session_log = (log_dir / f"session-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.log").open("w")
            process = subprocess.Popen(run_command(configs, stage_dir), cwd=EVAL_DIR, env=runner_env(),
                                       stdout=session_log, stderr=subprocess.STDOUT, start_new_session=True)
            holder, stop, verdict = {"dir": stage_dir}, threading.Event(), {}
            monitor = threading.Thread(target=_monitor, args=(holder, configs, process, stop, verdict), daemon=True)
            monitor.start()
            code = process.wait()
            stop.set()
            monitor.join()
            session_log.close()
            text = Path(session_log.name).read_text()
            if (found := find_stage(configs)) and len(found) == 1:
                write_progress(found[0], configs)
            if verdict.get("stop"):
                log(f"STOP: {verdict['stop']}")
                return 1
            paused = next((line for line in text.splitlines() if line.startswith("PAUSED:")), None)
            log(f"session {sessions} exited {code}{': ' + paused if paused else ''}")
            if code == 0:
                continue  # the loop finalises
            if code == 4 and paused and "session time limit" in paused:
                continue
            if code == 4 and paused:
                if outages >= OUTAGE_RESUMES:
                    log(f"STOP: paused again after {outages} outage resumes ({paused}); rerun this command later")
                    return 1
                outages += 1
                log(f"outage pause {outages}/{OUTAGE_RESUMES}: waiting {OUTAGE_WAIT_S} s before resuming")
                wait(OUTAGE_WAIT_S)
                continue
            if code in (2, 3):
                tail = "\n".join(text.splitlines()[-5:])
                log(f"STOP: the runner {'refused' if code == 2 else 'stopped on a cap'}:\n{tail}")
                return 1
            if crashes >= CRASH_RESUMES:
                log(f"STOP: the runner exited {code} {crashes + 1} times; see {session_log.name}")
                return 1
            crashes += 1
            log(f"the runner exited {code} (interrupted?); resuming from the last checkpoint ({crashes}/{CRASH_RESUMES})")
    finally:
        services.stop()


# --- recovery, reports, audit ---------------------------------------------------------------------

def merge_none(original_path: Path, out_dir: Path) -> Path:
    """The merged view of a result with no eligible failure (``recovered: 0``), so all four share a protocol."""
    original = json.loads(original_path.read_text())
    plan = rec.plan(original, results_path=str(original_path), results_sha256=rec.sha256_file(original_path))
    if plan["runs"]:
        raise ValueError(f"{original['experiment_id']} has recoverable runs")
    empty = {"protocol": rec.PROTOCOL, "recovers": {"experiment_id": original["experiment_id"]}, "videos": [],
             "complete": True, "usage": None}
    merged = rec.merge(original, empty, recovery_path="none (no eligible infrastructure-failed video-runs)",
                       recovery_sha256=None)
    merged["recovery"]["of"] = {"results": str(original_path), "results_sha256": plan["of"]["results_sha256"]}
    out = out_dir / f"{original['experiment_id']}-merged-original+recovery-v1.json"
    if out.exists():
        raise FileExistsError(out)
    out.write_text(json.dumps(merged, indent=2, default=str) + "\n")
    return out


def recovery_stages(results: dict[str, Path], results_root: Path = er.RESULTS_ROOT) -> list[Path]:
    return sorted(p for n, path in results.items()
                  for p in (results_root / f"{json.loads(path.read_text())['experiment_id']}-recovery").glob("*")
                  if p.is_dir()) if results else []


def recover(results: dict[str, Path], log_dir: Path) -> dict:
    """recovery-v1 of the eligible failures (dry run, then paid); returns the merged view per configuration."""
    plans = {n: rec.plan(json.loads(p.read_text()), results_path=str(p), results_sha256=rec.sha256_file(p))
             for n, p in results.items()}
    eligible = {n: p for n, p in plans.items() if p["runs"]}
    out = {"plans": {n: {"recover": len(p["runs"]), "runs": p["runs"], "not_recoverable": p["not_recoverable"]}
                     for n, p in plans.items()}, "merged": {}, "recovery_results": {}}
    for n, p in eligible.items():
        if len(p["runs"]) > rec.MAX_RECOVERED_RUNS:
            out["refused"] = f"{n}: {len(p['runs'])} eligible failures exceed {rec.MAX_RECOVERED_RUNS} (an outage)"
            return out
    if eligible:
        if existing := recovery_stages({n: results[n] for n in eligible}):
            out["refused"] = f"a Stage 3 recovery already exists ({existing}); it is never re-run automatically"
            return out
        paths = [str(results[n]) for n in eligible]
        base = [str(EVAL_DIR / ".venv" / "bin" / "python"), "scripts/eval_experiment.py", "recover", *paths]
        dry = subprocess.run(base, cwd=EVAL_DIR, env=runner_env(), capture_output=True, text=True, check=False)
        (log_dir / "recovery-dry-run.log").write_text(dry.stdout + dry.stderr)
        if dry.returncode != 0:
            out["refused"] = f"the recovery dry run failed: {dry.stderr[-500:]}"
            return out
        paid = subprocess.run(["experiments/keep-awake.sh", "--", *base, "--confirm-paid"], cwd=EVAL_DIR,
                              env=runner_env(), capture_output=True, text=True, check=False)
        (log_dir / "recovery.log").write_text(paid.stdout + paid.stderr)
        text = paid.stdout
        summary = json.loads(text[text.index("{\n  \"recovery\""):]) if "\"recovery\"" in text else None
        if paid.returncode != 0 or summary is None:
            out["refused"] = f"the recovery exited {paid.returncode}: {paid.stderr[-500:]}"
            return out
        for n, recovery_path, merged_path in zip(eligible, summary["recovery"], summary["merged"], strict=True):
            out["recovery_results"][n], out["merged"][n] = recovery_path, merged_path
    view = REPORTS_DIR / "recovery-adjusted-v1"
    view.mkdir(parents=True, exist_ok=True)
    for n, path in results.items():
        if n not in out["merged"]:
            out["merged"][n] = str(merge_none(path, view))
    return out


def write_reports(view: str, sources: dict[str, Path]) -> Path:
    out = REPORTS_DIR / view
    out.mkdir(parents=True, exist_ok=True)
    (out / "sources.txt").write_text("".join(f"{n}={p}\n" for n, p in sources.items()))
    args = [f"{n}={p}" for n, p in sources.items()]
    python = str(EVAL_DIR / ".venv" / "bin" / "python")
    for command in ([python, "scripts/eval_stage3.py", "report", "--title", f"Stage 3 ({view})", "--out", str(out),
                     *args],
                    [python, "scripts/eval_severity_report.py", "--baseline", "C2", "--title",
                     f"Stage 3 severity v1.3 ({view})", "--out", str(out / "severity-v1.3"), *args]):
        result = subprocess.run(command, cwd=EVAL_DIR, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"{command[1]} failed: {result.stderr[-500:]}")
    return out


def _schedule_digest(stage_dir: Path) -> str:
    schedule = json.loads((stage_dir / "schedule.json").read_text())
    names = schedule["configs"]
    order = [[o["repeat"], o["position"], o["incident_id"], names.index(o["config"])] for o in schedule["order"]]
    return stage3.sha256_text(json.dumps(order))


def audit(stage_dir: Path, configs: dict[str, dict], results: dict[str, Path], merged: dict[str, Path],
          original_sha256: dict[str, str], *, rematch=None) -> dict:
    """Phase 6: every check that the results are complete, unduplicated, linked, unchanged and reproducible."""
    manifest = json.loads(stage3.MANIFEST_PATH.read_text())
    split = json.loads(er.SPLIT_PATH.read_text())
    checks: dict[str, list[str]] = {}
    originals = {n: json.loads(p.read_text()) for n, p in results.items()}
    merged_records = {n: json.loads(Path(p).read_text()) for n, p in merged.items()}

    problems = []
    if _schedule_digest(stage_dir) != manifest["order"]["schedule_sha256"]:
        problems.append("the stage's schedule is not the manifest's run order")
    keys = [(r["experiment_id"], v["repeat"], v["incident_id"]) for r in originals.values() for v in r["videos"]]
    if len(keys) != 220 or len(set(keys)) != 220:
        problems.append(f"{len(keys)} original video-runs, {len(set(keys))} distinct (220 scheduled)")
    for n, record in originals.items():
        if sorted(v["incident_id"] for v in record["videos"]) != manifest["split"]["test"]:
            problems.append(f"{n}: its videos are not the 55 manifest clips")
    checks["accounted and unduplicated"] = problems

    problems = []
    for n, record in originals.items():
        pinned = manifest["configs"][n]
        file_config = json.loads((EVAL_DIR / pinned["file"]).read_text())
        if hashlib.sha256((EVAL_DIR / pinned["file"]).read_bytes()).hexdigest() != pinned["file_sha256"]:
            problems.append(f"{n}: the config file changed after pinning")
        if record["config"] != file_config:
            problems.append(f"{n}: the run's config is not the pinned config")
        if record["prompt"]["sha256"] != pinned["prompt_sha256"]:
            problems.append(f"{n}: prompt {record['prompt']['sha256'][:12]} is not the pinned one")
        if record["ground_truth"]["records_sha256"] != manifest["ground_truth"]["records_sha256"]:
            problems.append(f"{n}: scored against another ground truth")
        if (record["methodology"]["methodology_version"], record["methodology"]["match_threshold"]) != \
                (manifest["methodology"]["version"], manifest["methodology"]["match_threshold"]):
            problems.append(f"{n}: scored under another methodology")
        if record["model"] not in manifest["model"] or record["split"]["half"] != "test":
            problems.append(f"{n}: another model or split")
        problems += [f"{n}: {p}" for p in experiment_report.verify(results[n].parent, split=split,
                                                                  gt_manifest=manifest["ground_truth"])]
    checks["linked to the manifest"] = problems

    problems = []
    gt_file = stage3.GT_MANIFEST_PATH
    if hashlib.sha256(gt_file.read_bytes()).hexdigest() != manifest["ground_truth"]["manifest_sha256"]:
        problems.append("the frozen ground-truth manifest changed")
    if (methodology.METHODOLOGY_VERSION, methodology.MATCH_THRESHOLD) != \
            (manifest["methodology"]["version"], manifest["methodology"]["match_threshold"]):
        problems.append("the methodology in force changed")
    problems += [f"manifest drift: {p}" for p in stage3.manifest_problems(
        manifest, stage3.build_manifest(configs, split))]
    checks["ground truth and methodology unchanged"] = problems

    problems = []
    for n, path in results.items():
        if rec.sha256_file(path) != original_sha256[n]:
            problems.append(f"{n}: the original results changed after the stage")
    for n, record in merged_records.items():
        original = {(v["repeat"], v["incident_id"]): v for v in originals[n]["videos"]}
        if record.get("protocol") != rec.MERGED_PROTOCOL:
            problems.append(f"{n}: the merged view is not {rec.MERGED_PROTOCOL}")
        for video in record["videos"]:
            key = (video["repeat"], video["incident_id"])
            if "recovered_from" in video:
                before = original[key]
                if extraction_stats.has_model_output(before) or not rec.failure_class(before):
                    problems.append(f"{n} {key}: a recovered run whose original was not an eligible failure")
                if video["recovered_from"]["run_id"] != before.get("run_id"):
                    problems.append(f"{n} {key}: the recovery link does not name the original run")
            elif video != original[key]:
                problems.append(f"{n} {key}: a non-recovered run differs from its original")
        if record.get("reliability_original") != (originals[n].get("reliability")
                                                  or extraction_stats.reliability(originals[n]["videos"])):
            problems.append(f"{n}: original-run reliability is not preserved in the merged view")
    checks["original and recovered distinguishable"] = problems

    problems = []
    for view, sources in (("original", results), ("recovery-adjusted-v1", merged)):
        saved = REPORTS_DIR / view / "stage3-report.json"
        if not saved.exists():
            problems.append(f"{view}: no saved report")
            continue
        records = {n: json.loads(Path(p).read_text()) for n, p in sources.items()}
        again = json.loads(json.dumps(stage3.report(records), default=str))
        kept = {k: v for k, v in json.loads(saved.read_text()).items() if k != "sources"}
        if again != kept:
            problems.append(f"{view}: re-running the report from the saved results gives a different result")
    rematched = {}
    if rematch is not None:
        for n, record in originals.items():
            again = rematch(record)
            for before, after in zip(record["videos"], again["videos"], strict=True):
                for kind in ("entities", "instruments", "assets"):
                    a, b = (before.get(kind) or {}).get("counts"), (after.get(kind) or {}).get("counts")
                    if a and b and (a["tp"], a["fp"], a["fn"]) != (b["tp"], b["fp"], b["fn"]):
                        problems.append(f"{n} {before['incident_id']} {kind}: re-matching gives {b} not {a}")
            rematched[n] = True
    checks["reproducible from saved results"] = problems

    problems = []
    usage = {}
    for n, record in originals.items():
        used, cap = record["usage"], configs[n]["budget"]
        usage[n] = {"p1_attempts": used["p1_attempts"], "p1_tokens_reserved": used["p1_tokens_bound"],
                    "p1_tokens": used["p1_tokens"], "judge_calls": used["judge_calls"], "judge_tokens": used["judge_tokens"]}
        for key, limit in (("p1_attempts", "max_p1_calls"), ("p1_tokens_reserved", "max_p1_tokens"),
                           ("judge_calls", "max_judge_calls")):
            if usage[n][key] > cap[limit]:
                problems.append(f"{n}: {key} {usage[n][key]} over the cap {cap[limit]}")
    recovery_caps = stage3.stage_caps(configs, split)["configs"]
    for n, record in merged_records.items():
        used = (record.get("recovery") or {}).get("usage") or {}
        usage[n]["recovery"] = used
        if used.get("p1_attempts", 0) > recovery_caps[n]["recovery_max_p1_calls"]:
            problems.append(f"{n}: recovery used {used['p1_attempts']} attempts, over its cap")
    cost = _cost_log(stage_dir)
    if len(cost) != 220:
        problems.append(f"the stage cost log has {len(cost)} lines for 220 runs (a replayed or missing run)")
    if sum(c["p1_attempts"] for c in cost) != sum(u["p1_attempts"] for u in usage.values()):
        problems.append("the cost log's attempts differ from the results' usage")
    checks["within the approved budgets"] = problems

    files = {str(p): rec.sha256_file(Path(p)) for p in [*results.values(), *map(Path, merged.values())]}
    return {"ok": not any(checks.values()), "checks": checks, "usage": usage, "rematched": sorted(rematched),
            "manifest_sha256": rec.sha256_file(stage3.MANIFEST_PATH), "stage": str(stage_dir), "files_sha256": files,
            "at": datetime.now(UTC).isoformat(timespec="seconds")}


def _rematcher():
    """Item re-matching at the manifest's τ through the local embedder (no model or judge call)."""
    import item_rescore

    def rematch(record):
        return item_rescore.rematch(copy.deepcopy(record), threshold=methodology.MATCH_THRESHOLD,
                                    methodology_version=methodology.METHODOLOGY_VERSION, source="audit",
                                    source_sha256="audit", provisional=False)
    return rematch


def finalize(stage_dir: Path, configs: dict[str, dict], *, services: Services | None = None) -> int:
    """Phases 4-6 after the 220 runs: verify, recover, report both views, audit. Exit 0 only if the audit passes."""
    os.environ.setdefault("INCIDENT_EMBEDDING_BASE_URL", methodology.EMBEDDING_BASE_URL)
    log_dir = EVAL_DIR / "eval_data" / "results" / "stage3-supervisor"
    results = stage_results(stage_dir, configs)
    split = json.loads(er.SPLIT_PATH.read_text())
    gt = json.loads(stage3.GT_MANIFEST_PATH.read_text())
    for n, path in results.items():
        if problems := experiment_report.verify(path.parent, split=split, gt_manifest=gt):
            log(f"STOP: {n} does not verify: {problems}")
            return 1
    write_progress(stage_dir, configs)
    state_path = REPORTS_DIR / "finalize-state.json"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if "original_sha256" not in state:
        state["original_sha256"] = {n: rec.sha256_file(p) for n, p in results.items()}
        state_path.write_text(json.dumps(state, indent=2) + "\n")
    if "recovery" not in state:
        if services is not None and (problems := services.ensure()):
            log(f"STOP: {problems}")
            return 1
        outcome = recover(results, log_dir)
        if "refused" in outcome:
            log(f"STOP: recovery not run: {outcome['refused']}")
            (REPORTS_DIR / "recovery-refused.json").write_text(json.dumps(outcome, indent=2) + "\n")
            return 1
        state["recovery"] = outcome
        state_path.write_text(json.dumps(state, indent=2) + "\n")
    merged = {n: Path(p) for n, p in state["recovery"]["merged"].items()}
    if not (REPORTS_DIR / "original" / "stage3-report.json").exists():
        write_reports("original", results)
    if not (REPORTS_DIR / "recovery-adjusted-v1" / "stage3-report.json").exists():
        write_reports("recovery-adjusted-v1", merged)
    if services is not None:
        services.ensure()
    rematch = _rematcher() if healthy(EMBEDDER_HEALTH) else None
    result = audit(stage_dir, configs, results, merged, state["original_sha256"], rematch=rematch)
    if rematch is None:
        result["checks"].setdefault("reproducible from saved results", []).append(
            "item re-matching skipped: the embedder was not running")
        result["ok"] = False
    out = REPORTS_DIR / f"audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    log(f"audit {'PASSED' if result['ok'] else 'FAILED'}: {out}")
    if not result["ok"]:
        log(json.dumps({k: v for k, v in result["checks"].items() if v}, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(supervise())
