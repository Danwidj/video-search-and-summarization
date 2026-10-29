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
    uv run python scripts/eval_stage3.py progress                    # the stage's progress.json, no calls
    uv run python scripts/eval_stage3.py supervise                   # PAID (owner-approved): run or resume Stage 3,
                                                                     # then recover, report and audit

``report`` refuses to overwrite and only reads the results files. ``supervise`` is the single resumable launch
command: rerun it after any stop; it continues from the last checkpoint and never starts a second run.
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
    out = stage3.preflight_checks(skip_agent_parity=args.skip_agent_parity)
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


def cmd_progress(args) -> int:
    import stage3_automation as auto

    configs = stage3.load_configs()
    stages = auto.find_stage(configs)
    if len(stages) != 1:
        print(f"{len(stages)} Stage 3 stage directories: {stages}", file=sys.stderr)
        return 1
    print(json.dumps(auto.write_progress(stages[0], configs), indent=2))
    return 0


def cmd_supervise(args) -> int:
    import stage3_automation as auto

    return auto.supervise()


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
    sub.add_parser("progress")
    sub.add_parser("supervise", help="PAID: run or resume Stage 3, then recovery-v1, reports and the audit")
    args = parser.parse_args()
    return {"manifest": cmd_manifest, "preflight": cmd_preflight, "report": cmd_report, "progress": cmd_progress,
            "supervise": cmd_supervise}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
