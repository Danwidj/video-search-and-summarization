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

"""Severity report (evaluation-methodology-v1.3 reporting extension) from saved results: no model or judge call.

    uv run python scripts/eval_severity_report.py --baseline C2 --title "Stage 1" --out <dir> \\
        C1=<results.json> C2=<results.json>

Writes ``<dir>/severity-report-v1.3.json`` and ``.md``; refuses to overwrite. The results files are only read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL_DIR), str(EVAL_DIR / "scripts")]

import severity_metrics as sm  # noqa: E402


def _fmt(value, digits: int = 3) -> str:
    return "–" if value is None else (f"{value:.{digits}f}" if isinstance(value, float) else str(value))


def _ci(interval) -> str:
    return "–" if not interval else f"[{interval[0]:+.3f}, {interval[1]:+.3f}]"


def build(records: dict[str, dict], sources: dict[str, Path], baseline: str, title: str) -> tuple[dict, str]:
    summaries = {name: sm.summarise(r["videos"]) for name, r in records.items()}
    pairs = {name: sm.paired(records[baseline]["videos"], r["videos"]) for name, r in records.items() if name != baseline}
    report = {"report_version": sm.REPORT_VERSION, "title": title, "baseline": baseline,
              "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "sources": {n: {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                              "experiment_id": records[n]["experiment_id"],
                              "methodology_version": (records[n].get("methodology") or {}).get("methodology_version")}
                          for n, p in sources.items()},
              "summaries": summaries, "paired_against_baseline": pairs}
    lines = [f"# {title}: severity (methodology v1.3 reporting extension)", "",
             "> Reporting only: MAE is the primary *severity-specific* metric. Prompt selection stays D9 v2, "
             "whose severity component is exact accuracy, unchanged. Computed offline from saved outputs.", "",
             "| Config | Attempted | Valid | Coverage | **MAE** | Signed error | Exact | Within ±1 | Over / under |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, s in summaries.items():
        lines.append(f"| {name} | {s['attempted']} | {s['valid']} | {_fmt(s['coverage'])} | **{_fmt(s['mae'])}** | "
                     f"{_fmt(s['mean_signed_error'], 3)} | {_fmt(s['exact'])} | {_fmt(s['within_one'])} | "
                     f"{s['over_rated']} / {s['under_rated']} |")
    if pairs:
        lines += ["", f"## Paired against {baseline} (per video, repeats averaged; 95% video-cluster bootstrap)", "",
                  "| Config | Pairs | MAE (baseline → config) | MAE difference | 95% CI | Signed-error difference | 95% CI |",
                  "|---|---|---|---|---|---|---|"]
        for name, p in pairs.items():
            lines.append(f"| {name} | {p['pairs']} | {_fmt(p['baseline_mae_on_pairs'])} → {_fmt(p['candidate_mae_on_pairs'])} "
                         f"| {_fmt(p['mae_difference'])} | {_ci(p['mae_difference_ci95'])} | "
                         f"{_fmt(p['signed_error_difference'])} | {_ci(p['signed_error_difference_ci95'])} |")
    lines += ["", "Failures without a valid severity (not given a value): " +
              "; ".join(f"{n}: {s['failure_categories'] or 'none'}" for n, s in summaries.items()), ""]
    return report, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("configurations", nargs="+", help="NAME=<results.json>")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = {}
    for item in args.configurations:
        name, _, path = item.partition("=")
        sources[name] = Path(path)
    if args.baseline not in sources:
        print("REFUSED: --baseline must name one of the configurations", file=sys.stderr)
        return 2
    records = {n: json.loads(p.read_text()) for n, p in sources.items()}
    report, markdown = build(records, sources, args.baseline, args.title)
    args.out.mkdir(parents=True, exist_ok=True)
    targets = (args.out / "severity-report-v1.3.json", args.out / "severity-report-v1.3.md")
    if any(t.exists() for t in targets):
        print(f"REFUSED: a report exists in {args.out}", file=sys.stderr)
        return 2
    targets[0].write_text(json.dumps(report, indent=2) + "\n")
    targets[1].write_text(markdown)
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
