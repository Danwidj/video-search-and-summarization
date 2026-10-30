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

"""End-to-end VSS profile manifest, offline preflight and report (see ``e2e_profile.py``). Sends no request.

Usage (from ``eval/``)::

    uv run python scripts/eval_e2e_profile.py manifest [--write]   # build (and pin) experiments/e2e-profile/manifest.json
    uv run python scripts/eval_e2e_profile.py preflight            # every offline check; exit 1 on any problem
    uv run python scripts/eval_e2e_profile.py report --title "…" --out <new dir> C2=<results.json> C3=<results.json>

The paid run itself (only after the owner approves its budget) is the experiment runner on the two configs::

    experiments/keep-awake.sh -- .venv/bin/python scripts/eval_experiment.py run \\
        experiments/configs/e2e-c2-vss-base.json experiments/configs/e2e-c3-vss-v1.json --confirm-paid
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL_DIR), str(EVAL_DIR / "scripts")]

import e2e_profile  # noqa: E402
import experiment_runner as er  # noqa: E402


def cmd_manifest(args) -> int:
    manifest = e2e_profile.build_manifest(e2e_profile.load_configs(), json.loads(er.SPLIT_PATH.read_text()))
    if args.write:
        e2e_profile.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        e2e_profile.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_preflight(args) -> int:
    out = e2e_profile.preflight_checks(skip_agent_check=args.skip_agent_check)
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def cmd_report(args) -> int:
    sources = {name: Path(path) for name, _, path in (item.partition("=") for item in args.configurations)}
    targets = (args.out / "e2e-profile-report.json", args.out / "e2e-profile-report.md")
    if any(t.exists() for t in targets):
        print(f"REFUSED: a report exists in {args.out}", file=sys.stderr)
        return 2
    summary = e2e_profile.report({n: json.loads(p.read_text()) for n, p in sources.items()})
    summary["sources"] = {n: {"path": str(p), "sha256": e2e_profile.stage3.rec.sha256_file(p)} for n, p in sources.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(summary, indent=2, default=str) + "\n")
    targets[1].write_text(e2e_profile.render(summary, args.title))
    print(targets[1].read_text())
    return 0 if not summary["problems"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest").add_argument("--write", action="store_true")
    sub.add_parser("preflight").add_argument("--skip-agent-check", action="store_true",
                                             help="No agent venv here (never passes)")
    report = sub.add_parser("report")
    report.add_argument("configurations", nargs="+", help="NAME=<results.json>, NAME one of C2, C3")
    report.add_argument("--title", required=True)
    report.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return {"manifest": cmd_manifest, "preflight": cmd_preflight, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
