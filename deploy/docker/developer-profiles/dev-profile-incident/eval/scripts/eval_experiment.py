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

"""Plan, run, re-score and compare prompt experiments (PR 6A; see ``experiment_runner.py``).

Usage (from ``eval/``)::

    uv run python scripts/eval_experiment.py plan experiments/configs/direct-vlm-baseline.json   # no calls
    uv run python scripts/eval_experiment.py run  experiments/configs/direct-vlm-baseline.json --confirm-paid
    uv run python scripts/eval_experiment.py run  <config> <config> ... --confirm-paid   # interleaved stage (D10)
    uv run python scripts/eval_experiment.py rescore <results.json> --confirm-paid   # judge calls, no P1 calls
    uv run python scripts/eval_experiment.py compare C1=<results.json> C2=<…> C3=<…> C4=<…>
    uv run python scripts/eval_experiment.py report --title "…" C1=<results.json> …  > report.md
    uv run python scripts/eval_experiment.py verify <results dir>
    uv run python scripts/eval_experiment.py budget experiments/configs/*.json [--measured measured.json]
    uv run python scripts/eval_experiment.py measure <results.json> ...   # pilot figures for budget --measured

``run`` and ``rescore`` make paid calls (P1 and/or the LLM judge) and refuse without
``--confirm-paid``; ``plan``, ``compare``, ``report``, ``verify``, ``budget`` and ``measure`` make none.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import experiment_runner as er  # noqa: E402
import prompt_registry  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1]
DATASET_MANIFEST = EVAL_DIR / "eval_reproducibility" / "dataset-manifest-v1.json"


def _cell(column: str, value):
    """Frozen JSON stores datetimes as text; give ``write_gt`` the datetime the workbook would hold."""
    if column == "Labelled_DateTime" and isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return value


def frozen_store(sheets: dict):
    """An offline store holding the frozen ground truth, through the same ``write_gt`` path as the workbook."""
    import ground_truth_freeze
    import openpyxl
    from eval_ingest_gt import write_gt
    from offline_store import OfflineEvalStore

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for sheet, columns in ground_truth_freeze.COLUMNS.items():
        ws = workbook.create_sheet(sheet)
        ws.append(columns)
        for record in sheets[sheet]:
            ws.append([_cell(column, record.get(column)) for column in columns])
    store = OfflineEvalStore()
    write_gt(store, workbook)
    return store


def load_gt(config: dict) -> tuple[dict, dict]:
    """``(index, sheets)`` of the config's frozen ground truth, checksums verified."""
    import eval_gt_schema
    import ground_truth_freeze

    directory = EVAL_DIR / config["ground_truth"]["dir"]
    allow = bool(config["ground_truth"].get("allow_candidate"))
    index = eval_gt_schema.load_frozen_gt_index(directory, allow_candidate=allow)
    return index, ground_truth_freeze.read_frozen(directory, allow_candidate=allow)["sheets"]


def video_source_from_manifest():
    import r2_videos  # noqa: F401  (credentials are read on first signing)
    from eval_video_resolution import signed_url

    clips = {c["incident_id"]: c for c in json.loads(DATASET_MANIFEST.read_text())["clips"]}

    def source(incident_id: str):
        clip = clips[incident_id]
        return signed_url(clip["r2_key"]), {"r2_object_key": clip["r2_key"], "duration_seconds": clip["duration_seconds"],
                                            "size_bytes": clip["size_bytes"]}

    return source


def cmd_plan(args) -> int:
    config = er.load_config(args.config)
    split = json.loads(er.SPLIT_PATH.read_text())
    try:
        print(json.dumps(er.preflight(config, split), indent=2))
    except er.ExperimentRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


def call_factory_for(config: dict):
    """The P1 call of a configuration's arm (``experiment_runner.direct_call`` or ``vss_call``)."""
    item = prompt_registry.entry(config["prompt_id"])
    text = prompt_registry.prompt_text(config["prompt_id"])
    if config["arm"] == "direct-vlm":
        return lambda incident_id, run_id, duration, max_retries=None: er.direct_call(
            text, max_retries=max_retries, policy=er.retry_policy(config))
    return lambda incident_id, run_id, duration, max_retries=None: er.vss_call(
        config, item, incident_id=incident_id, run_id=run_id, duration=duration, max_retries=max_retries)


def host_guard(args) -> str | None:
    """A paid run on WSL must hold a wake request (experiments/keep-awake.sh), unless --allow-sleep says otherwise."""
    if getattr(args, "allow_sleep", False) or os.environ.get("KEEP_AWAKE_ACTIVE") == "1":
        return None
    try:
        wsl = "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        wsl = False
    return ("on WSL a paid run needs a wake request: run it under experiments/keep-awake.sh -- ... (lid open, on AC), "
            "or pass --allow-sleep") if wsl else None


def cmd_run(args) -> int:
    """One configuration, or several run interleaved as one stage (D10), under their hard caps (D11)."""
    import eval_run

    configs = [er.load_config(path) for path in args.configs]
    split = json.loads(er.SPLIT_PATH.read_text())
    try:
        out = er.run_stage(configs, split=split, gt_index={}, store=None, video_source=None, call_factory_for=None,
                           run_one=None, confirm_paid=False)
        if not args.confirm_paid:
            print(json.dumps({"dry_run": True, "plans": out["plans"],
                              "order_seed": er.ORDER_SEED, "pricing": er.load_pricing()}, indent=2))
            print("Nothing sent. Re-run with --confirm-paid after this stage's budget is approved.", file=sys.stderr)
            return 0
        if (problem := host_guard(args)) is not None:
            raise er.ExperimentRefused(problem)
        if len({c["ground_truth"]["dir"] for c in configs}) != 1:
            raise er.ExperimentRefused("configurations in one stage must use the same ground truth")
        gt_index, sheets = load_gt(configs[0])
        # The embedding server is only needed when items are matched (scoring: full).
        eval_run.evaluator_preflight(incident_only=all(c["scoring"] == "incident_only" for c in configs))
        result = er.run_stage(configs, split=split, gt_index=gt_index, store=frozen_store(sheets),
                              video_source=video_source_from_manifest(), call_factory_for=call_factory_for,
                              run_one=eval_run.run_one_video, confirm_paid=True, resume=args.resume)
    except er.ExperimentRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"results": result["results_files"], "stage": result["stage_dir"], "stopped": result["stopped"],
                      "usage": {r["experiment_id"]: r["usage"] for r in result["records"]}}, indent=2))
    return 0 if result["stopped"] is None else 3


def cmd_rescore(args) -> int:
    """Re-score saved raw outputs with the current scorer: no P1 call (the judge is called)."""
    import eval_run
    from eval_vlm_client import ChatResult, P1Outcome

    saved = json.loads(args.results.read_text())
    if not args.confirm_paid:
        print(f"REFUSED: re-scoring calls the LLM judge for {len(saved['videos'])} videos; pass --confirm-paid",
              file=sys.stderr)
        return 2
    gt_index, sheets = load_gt(saved["config"])
    eval_run.evaluator_preflight()
    store = frozen_store(sheets)
    videos = []
    for video in saved["videos"]:
        raw = video["p1_raw"]
        outcome = P1Outcome(result=ChatResult(ok=raw["ok"], content=raw["content"], error=raw["error"],
                                              failure_kind=raw["failure_kind"], status_code=raw["status_code"],
                                              finish_reason=raw["finish_reason"]), attempts=[])
        store.insert_model_run(video["run_id"], model_name=video["model_id"])
        entry = gt_index["by_incident_id"][video["incident_id"]]
        rescored = eval_run.run_one_video(
            store, model=video["model_id"], category=entry["category"], filename=entry["filename"],
            incident_id=video["incident_id"], r2_object_key=video["r2_object_key"], video_url="(saved output)",
            gt_p1_shaped=entry["p1_shaped"], model_run_id=video["run_id"], split_manifest_ref=video["split_manifest_ref"],
            video_duration_seconds=video["video"]["duration_seconds"], p1_call=lambda *_a, o=outcome: o)
        videos.append({**rescored, "repeat": video.get("repeat"), "arm": video.get("arm"),
                       "prompt_id": video.get("prompt_id"), "timing": video["timing"]})
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.results.parent / f"rescored-{stamp}.json"
    out.write_text(json.dumps({**saved, "videos": videos, "rescored_from": str(args.results), "rescored_at": stamp},
                              indent=2, default=str) + "\n")
    print(out)
    return 0


def cmd_recover(args) -> int:
    """recovery-v1: re-attempt only the infrastructure-failed video-runs of saved results (dry run by default)."""
    import eval_run
    import experiment_recovery as rec

    originals = [(path, json.loads(path.read_text())) for path in args.results]
    plans = [rec.plan(record, results_path=str(path), results_sha256=rec.sha256_file(path)) for path, record in originals]
    gt_index, sheets = load_gt(originals[0][1]["config"])
    try:
        configs = [rec.recovery_config(record["config"], p, gt_index, max_runs=args.max_runs)
                   for (_, record), p in zip(originals, plans, strict=True)]
    except rec.RecoveryRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    only = {c["experiment_id"]: {(r["repeat"], r["incident_id"]) for r in p["runs"]}
            for c, p in zip(configs, plans, strict=True)}
    summary = {"protocol": rec.PROTOCOL, "retry_policy": rec.RECOVERY_RETRY_POLICY,
               "plans": [{"experiment_id": p["experiment_id"], "recover": len(p["runs"]),
                          "by_class": {k: sum(1 for r in p["runs"] if r["class"] == k) for k in rec.RECOVERABLE},
                          "not_recoverable": p["not_recoverable"]} for p in plans],
               "budgets": {c["experiment_id"]: c["budget"] for c in configs}}
    if not args.confirm_paid:
        print(json.dumps(summary, indent=2))
        print("Nothing sent. Re-run with --confirm-paid after the recovery budget is approved.", file=sys.stderr)
        return 0
    split = json.loads(er.SPLIT_PATH.read_text())
    try:
        if (problem := host_guard(args)) is not None:
            raise er.ExperimentRefused(problem)
        eval_run.evaluator_preflight()
        result = er.run_stage(configs, split=split, gt_index=gt_index, store=frozen_store(sheets),
                              video_source=video_source_from_manifest(), call_factory_for=call_factory_for,
                              run_one=eval_run.run_one_video, confirm_paid=True, only=only,
                              recovery={c["experiment_id"]: rec.links(p) for c, p in zip(configs, plans, strict=True)})
    except er.ExperimentRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    merged = []
    for (_, original), path in zip(originals, result["results_files"], strict=True):
        recovery_path = Path(path)
        record = rec.merge(original, json.loads(recovery_path.read_text()), recovery_path=str(recovery_path),
                           recovery_sha256=rec.sha256_file(recovery_path))
        out = recovery_path.parent / "merged-original+recovery-v1.json"
        out.write_text(json.dumps(record, indent=2, default=str) + "\n")
        merged.append(str(out))
    print(json.dumps({"recovery": result["results_files"], "merged": merged, "stopped": result["stopped"]}, indent=2))
    return 0 if result["stopped"] is None else 3


def cmd_rematch(args) -> int:
    """Re-match a saved result's items under another methodology version's threshold: no model or judge call."""
    import hashlib

    import item_rescore
    import methodology

    if args.methodology not in methodology.MATCH_THRESHOLDS:
        print(f"REFUSED: unknown methodology {args.methodology!r}", file=sys.stderr)
        return 2
    threshold = args.threshold if args.threshold is not None else methodology.MATCH_THRESHOLDS[args.methodology]
    provisional = args.threshold is not None  # an override is a sensitivity check, never the methodology's value
    content = args.results.read_bytes()
    record = item_rescore.rematch(json.loads(content), threshold=threshold, methodology_version=args.methodology,
                                  source=str(args.results), source_sha256=hashlib.sha256(content).hexdigest(),
                                  provisional=provisional)
    tag = args.methodology.removeprefix("evaluation-methodology-") + f"-t{threshold:.2f}"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.results.parent / f"rematched-{tag}-{stamp}.json"
    out.write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(out)
    return 0


def cmd_compare(args) -> int:
    print(json.dumps(er.four_way(_named(args.configurations)), indent=2))
    return 0


def _named(items: list[str]) -> dict[str, dict]:
    records = {}
    for item in items:
        name, _, path = item.partition("=")
        records[name] = json.loads(Path(path).read_text())
    return records


def cmd_report(args) -> int:
    import experiment_report

    print(experiment_report.render(_named(args.configurations), title=args.title))
    return 0


def cmd_verify(args) -> int:
    import experiment_report
    import ground_truth_freeze

    record = json.loads((args.results_dir / "results.json").read_text())
    gt_dir = EVAL_DIR / record["config"]["ground_truth"]["dir"]
    manifest = json.loads((gt_dir / "MANIFEST.json").read_text()) if (gt_dir / "MANIFEST.json").exists() else None
    if manifest is not None:
        ground_truth_freeze.read_frozen(gt_dir, allow_candidate=True)  # checksums of the ground truth itself
    problems = experiment_report.verify(args.results_dir, split=json.loads(er.SPLIT_PATH.read_text()),
                                        gt_manifest=manifest)
    for problem in problems:
        print(f"  {problem}")
    print("verify:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


def cmd_budget(args) -> int:
    import experiment_report

    measured = json.loads(args.measured.read_text()) if args.measured else None
    configs = [er.load_config(path) for path in args.configs]
    print(json.dumps(experiment_report.budget(configs, json.loads(er.SPLIT_PATH.read_text()), measured=measured),
                     indent=2))
    return 0


def cmd_caps(args) -> int:
    """Derive each config's judge-request cap from the ground truth (no calls); --write updates the snapshot."""
    split = json.loads(er.SPLIT_PATH.read_text())
    configs = [er.load_config(path) for path in args.configs]
    gt_index, _ = load_gt({**configs[0], "ground_truth": {**configs[0]["ground_truth"], "allow_candidate": True}})
    rows = [er.judge_cap_required(c, split, gt_index) for c in configs]
    snapshot = {"ground_truth": {"version": gt_index.get("version"), "status": gt_index.get("status"),
                                 "records_sha256": gt_index["manifest"].get("records_sha256")},
                "attempts_per_field": er.JUDGE_ATTEMPTS_PER_FIELD,
                "formula": "required = repeats x sum(judged fields per video) x attempts per field; judged fields = "
                           "1 (incident description) + entities + 2 x instruments + 2 x assets (full scoring)",
                "configs": rows}
    if args.write:
        er.JUDGE_CAPS_PATH.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({**snapshot, "configs": [{k: v for k, v in r.items() if k != "per_video"} for r in rows]},
                     indent=2))
    return 0 if all(r["configured"] >= r["required"] for r in rows) else 1


def cmd_measure(args) -> int:
    """Pilot measurements (tokens and judge calls per call, rate limiting, latency) for ``budget --measured``."""
    import experiment_report

    records = [json.loads(path.read_text()) for path in args.results]
    print(json.dumps(experiment_report.measure(records), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt experiments: plan, run, rescore, compare.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("config", type=Path)
    run = sub.add_parser("run", help="One config, or several interleaved as one stage")
    run.add_argument("configs", nargs="+", type=Path)
    run.add_argument("--confirm-paid", action="store_true")
    run.add_argument("--resume", type=Path, help="Continue an interrupted stage from its stage directory")
    run.add_argument("--allow-sleep", action="store_true", help="Skip the WSL keep-awake requirement")
    rescore = sub.add_parser("rescore")
    rescore.add_argument("results", type=Path)
    rescore.add_argument("--confirm-paid", action="store_true")
    recover = sub.add_parser("recover", help="recovery-v1 of infrastructure-failed video-runs (dry run by default)")
    recover.add_argument("results", nargs="+", type=Path)
    recover.add_argument("--confirm-paid", action="store_true")
    recover.add_argument("--allow-sleep", action="store_true")
    recover.add_argument("--max-runs", type=int, default=15, help="Refuse when a config has more failed runs than this")
    rematch = sub.add_parser("rematch", help="Re-match items offline at a methodology version's threshold")
    rematch.add_argument("results", type=Path)
    rematch.add_argument("--methodology", required=True)
    rematch.add_argument("--threshold", type=float, help="Override (sensitivity only; marked provisional)")
    compare = sub.add_parser("compare")
    compare.add_argument("configurations", nargs="+", help="C1=<results.json> ...")
    report = sub.add_parser("report")
    report.add_argument("--title", required=True)
    report.add_argument("configurations", nargs="+", help="NAME=<results.json> ...")
    verify = sub.add_parser("verify")
    verify.add_argument("results_dir", type=Path)
    budget = sub.add_parser("budget")
    budget.add_argument("configs", nargs="+", type=Path)
    budget.add_argument("--measured", type=Path, help="Pilot measurements from 'measure' (replaces the estimates)")
    caps = sub.add_parser("caps", help="Derive judge-request caps from the ground truth (no calls)")
    caps.add_argument("configs", nargs="+", type=Path)
    caps.add_argument("--write", action="store_true", help="Update experiments/judge-caps.json")
    measure = sub.add_parser("measure")
    measure.add_argument("results", nargs="+", type=Path)
    args = parser.parse_args()
    return {"plan": cmd_plan, "run": cmd_run, "rescore": cmd_rescore, "rematch": cmd_rematch, "recover": cmd_recover, "compare": cmd_compare, "report": cmd_report,
            "verify": cmd_verify, "budget": cmd_budget, "measure": cmd_measure, "caps": cmd_caps}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
