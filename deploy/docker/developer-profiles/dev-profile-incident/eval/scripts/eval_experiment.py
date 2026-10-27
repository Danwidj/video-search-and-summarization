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
    uv run python scripts/eval_experiment.py rescore <results.json> --confirm-paid   # judge calls, no P1 calls
    uv run python scripts/eval_experiment.py compare C1=<results.json> C2=<…> C3=<…> C4=<…>

``run`` and ``rescore`` make paid calls (P1 and/or the LLM judge) and refuse without
``--confirm-paid``; ``plan`` and ``compare`` make none.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import experiment_runner as er  # noqa: E402
import prompt_registry  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1]
DATASET_MANIFEST = EVAL_DIR / "eval_reproducibility" / "dataset-manifest-v1.json"


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
            ws.append([record.get(c) for c in columns])
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


def cmd_run(args) -> int:
    import eval_run

    config = er.load_config(args.config)
    split = json.loads(er.SPLIT_PATH.read_text())
    try:
        plan = er.preflight(config, split)
        if not args.confirm_paid:
            print(json.dumps({"dry_run": True, "plan": plan}, indent=2))
            print("Nothing sent. Re-run with --confirm-paid after the budget for this stage is approved.", file=sys.stderr)
            return 0
        gt_index, sheets = load_gt(config)
        eval_run.evaluator_preflight()
        item = prompt_registry.entry(config["prompt_id"])
        text = prompt_registry.prompt_text(config["prompt_id"])
        if config["arm"] == "direct-vlm":
            factory = lambda incident_id, run_id, duration: er.direct_call(text)  # noqa: E731
        else:
            factory = lambda incident_id, run_id, duration: er.vss_call(  # noqa: E731
                config, item, incident_id=incident_id, run_id=run_id, duration=duration)
        result = er.run_experiment(config, split=split, gt_index=gt_index, store=frozen_store(sheets),
                                   video_source=video_source_from_manifest(), call_factory=factory,
                                   run_one=eval_run.run_one_video, confirm_paid=True)
    except er.ExperimentRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"results": result["results"], "reliability": result["record"]["reliability"]}, indent=2))
    return 0


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


def cmd_compare(args) -> int:
    records = {}
    for item in args.configurations:
        name, _, path = item.partition("=")
        records[name] = json.loads(Path(path).read_text())
    print(json.dumps(er.four_way(records), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt experiments: plan, run, rescore, compare.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("config", type=Path)
    run = sub.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("--confirm-paid", action="store_true")
    rescore = sub.add_parser("rescore")
    rescore.add_argument("results", type=Path)
    rescore.add_argument("--confirm-paid", action="store_true")
    compare = sub.add_parser("compare")
    compare.add_argument("configurations", nargs="+", help="C1=<results.json> ...")
    args = parser.parse_args()
    return {"plan": cmd_plan, "run": cmd_run, "rescore": cmd_rescore, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
