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

"""Stage 3 manifest, offline preflight and report (see ``stage3.py``). Sends no model or judge request.

Usage (from ``eval/``)::

    uv run python scripts/eval_stage3.py manifest [--write]   # build (and pin) experiments/stage3/manifest.json
    uv run python scripts/eval_stage3.py preflight            # every offline check; exit 1 on any problem
    uv run python scripts/eval_stage3.py report --title "…" --out <new dir> C1=<results.json> C2=… C3=… C4=…

``report`` refuses to overwrite and only reads the results files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL_DIR), str(EVAL_DIR / "scripts")]

import experiment_runner as er  # noqa: E402
import stage3  # noqa: E402

DATASET_MANIFEST = EVAL_DIR / "eval_reproducibility" / "dataset-manifest-v1.json"


def _split() -> dict:
    return json.loads(er.SPLIT_PATH.read_text())


def cmd_manifest(args) -> int:
    manifest = stage3.build_manifest(stage3.load_configs(), _split())
    if args.write:
        stage3.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        stage3.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_preflight(args) -> int:
    import eval_experiment

    configs, split = stage3.load_configs(), _split()
    gt_index, _ = eval_experiment.load_gt(configs["C1"])
    checks = {"roles": stage3.role_problems(configs), "shared settings": stage3.shared_setting_problems(configs),
              "runner guards": [f"{n}: {p}" for n, c in configs.items() for p in er.config_problems(c)]}
    try:
        for config in configs.values():
            er.preflight(config, split)
    except er.ExperimentRefused as exc:
        checks["runner guards"].append(str(exc))
    committed = json.loads(stage3.MANIFEST_PATH.read_text()) if stage3.MANIFEST_PATH.exists() else {}
    checks["manifest"] = stage3.manifest_problems(committed, stage3.build_manifest(configs, split)) if committed \
        else ["experiments/stage3/manifest.json is missing"]
    checks["ground truth"] = [] if gt_index["manifest"].get("records_sha256") == committed.get("ground_truth", {}).get(
        "records_sha256") else ["the loaded frozen ground truth does not match the manifest digest"]
    checks["test clips"] = stage3.clip_problems(split, json.loads(DATASET_MANIFEST.read_text()), gt_index)
    checks["caps"] = stage3.cap_problems(configs, split, gt_index)
    checks["run once"] = stage3.run_once_problems(configs)
    parity = None
    if args.skip_agent_parity:
        checks["request parity"] = ["skipped (--skip-agent-parity): not a passing preflight"]
    else:
        parity = stage3.parity(configs)
        checks["request parity"] = [f"{pair}: {row['differences']}" for pair, row in parity.items() if row["differences"]]
    out = {"ok": not any(checks.values()), "checks": checks, "request_parity": parity,
           "caps": stage3.stage_caps(configs, split, gt_index), "expected": stage3.expected_usage(configs, split, gt_index)}
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def cmd_report(args) -> int:
    sources = {}
    for item in args.configurations:
        name, _, path = item.partition("=")
        sources[name] = Path(path)
    records = {n: json.loads(p.read_text()) for n, p in sources.items()}
    targets = (args.out / "stage3-report.json", args.out / "stage3-report.md")
    if any(t.exists() for t in targets):
        print(f"REFUSED: a report exists in {args.out}", file=sys.stderr)
        return 2
    summary = stage3.report(records)
    summary["sources"] = {n: {"path": str(p), "sha256": stage3.rec.sha256_file(p)} for n, p in sources.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(summary, indent=2, default=str) + "\n")
    targets[1].write_text(stage3.render(summary, records, title=args.title))
    print(targets[1].read_text())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--write", action="store_true")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--skip-agent-parity", action="store_true", help="No agent venv here (never passes)")
    report = sub.add_parser("report")
    report.add_argument("configurations", nargs="+", help="NAME=<results.json>, NAME one of C1-C4")
    report.add_argument("--title", required=True)
    report.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return {"manifest": cmd_manifest, "preflight": cmd_preflight, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
