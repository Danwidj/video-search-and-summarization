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

"""Regenerate RP1 (report generation) output only, from the already-persisted
P1 structured predictions in ``eval_data/results/*.json`` - never re-runs P1
video inference, never re-scores against ground truth. Every other field of
every video record (``ground_truth``, ``prediction``, ``p1_raw``,
``incident_field_scores``, ``entities``/``instruments``/``assets``) is
verified byte-for-byte unchanged before the file is written back; only
``rp1_report`` is replaced.

Fixes applied vs. the original run (see eval_run_lib.py / eval_run.py):
  - RP1_INFERENCE_CONFIG now sets chat_template_kwargs.enable_thinking=False,
    so this reasoning model returns a direct final answer instead of
    exhausting max_tokens on internal chain-of-thought.
  - reasoning_content is never treated as a valid report; missing/empty final
    content is recorded as an explicit failure (ok=False), with a bounded
    retry (see generate_rp1_report in eval_run.py).

Usage::

    .venv/bin/python3 scripts/eval_regenerate_rp1.py                    # all 165
    .venv/bin/python3 scripts/eval_regenerate_rp1.py --models nvidia/cosmos-3-nano-reasoner --categories Assault --limit 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: F401,E402
from eval_run import generate_rp1_report  # noqa: E402
from eval_ingest_gt import EVAL_DATA_DIR  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"

_NON_RP1_KEYS = (
    "filename", "incident_id", "category", "model_id", "prompt_version", "inference_config",
    "split_manifest_ref", "run_id", "r2_object_key", "ground_truth", "prediction", "p1_raw",
    "incident_field_scores", "entities", "instruments", "assets",
)


def regenerate_file(path: Path, *, limit: int | None = None) -> dict:
    """Regenerate every video's ``rp1_report`` in one result file. Returns counts."""
    data = json.loads(path.read_text())
    videos = data["videos"]
    target = videos[:limit] if limit else videos

    counts = {"total": 0, "valid": 0, "failed": 0, "retries": 0}
    for video in target:
        before = {k: video.get(k) for k in _NON_RP1_KEYS}
        prediction = video["prediction"]

        new_report = generate_rp1_report(prediction)
        video["rp1_report"] = new_report

        after = {k: video.get(k) for k in _NON_RP1_KEYS}
        if before != after:
            raise AssertionError(
                f"regenerate_file: a non-rp1_report field changed for {video.get('filename')} in {path.name} - "
                "P1 predictions/GT/scores must never be touched by RP1 regeneration"
            )

        counts["total"] += 1
        if new_report["ok"]:
            counts["valid"] += 1
        else:
            counts["failed"] += 1
        counts["retries"] += max(0, new_report["attempts"] - 1)

        status = "ok" if new_report["ok"] else f"FAILED ({new_report['error'][:80]})"
        print(f"  {video['filename']}: {status}, attempts={new_report['attempts']}")

    path.write_text(json.dumps(data, indent=2))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=None, help="Filter to these model_id values (default: all)")
    parser.add_argument("--categories", nargs="*", default=None, help="Filter to these categories (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="Cap videos regenerated per file (debugging only)")
    args = parser.parse_args()

    files = sorted(p for p in RESULTS_DIR.glob("*.json") if p.name != "summary.json")
    if not files:
        raise SystemExit(f"No result files found under {RESULTS_DIR}")

    totals = {"total": 0, "valid": 0, "failed": 0, "retries": 0}
    for path in files:
        data = json.loads(path.read_text())
        if args.models and data["model_id"] not in args.models:
            continue
        if args.categories and data["category"] not in args.categories:
            continue

        print(f"=== {path.name} ({data['category']} / {data['model_id']}) ===")
        counts = regenerate_file(path, limit=args.limit)
        for k in totals:
            totals[k] += counts[k]
        print(f"  -> {counts['valid']}/{counts['total']} valid, {counts['failed']} failed, {counts['retries']} retries")
        print()

    print("=" * 60)
    print(f"TOTAL: {totals['valid']}/{totals['total']} valid reports, {totals['failed']} failed, {totals['retries']} retries")


if __name__ == "__main__":
    main()
