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

"""Snapshot, list and verify local backups of the ground-truth review workbook (no shared storage).

Usage (from ``eval/``)::

    uv run python scripts/gt_review_backup.py snapshot --reason "end of review session 1"
    uv run python scripts/gt_review_backup.py list
    uv run python scripts/gt_review_backup.py verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import review_backup  # noqa: E402

REVIEW_DIR = Path(__file__).resolve().parents[1] / "ground_truth" / "review"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="Copy the workbook to a timestamped backup and log it.")
    snapshot.add_argument("--version", default="v0.1")
    snapshot.add_argument("--kind", choices=("Review", "Candidate", "AI-Adjudicated Candidate"), default="Review",
                          help="Ground Truth Review <version> (PR 3) or Ground Truth Candidate <version> (PR 4)")
    snapshot.add_argument("--reason", required=True)
    sub.add_parser("list", help="Show the backup log.")
    sub.add_parser("verify", help="Check every logged backup still exists with its recorded SHA-256.")
    args = parser.parse_args()

    if args.command == "snapshot":
        workbook = REVIEW_DIR / f"Ground Truth {args.kind} {args.version}.xlsx"
        if not workbook.exists():
            print(f"no workbook at {workbook}", file=sys.stderr)
            return 1
        if review_backup.lock_file(workbook).exists():
            print("note: the workbook is open in Excel; the snapshot holds its last saved state", file=sys.stderr)
        record = review_backup.backup(workbook, reason=args.reason)
        print(json.dumps(record, indent=2))
        return 0
    log = REVIEW_DIR / review_backup.BACKUP_DIR_NAME / review_backup.BACKUP_LOG
    if args.command == "list":
        for line in (log.read_text().splitlines() if log.exists() else []):
            record = json.loads(line)
            print(f"{record['time']}  {record['backup']}  sha256 {record['sha256'][:12]}  "
                  f"decisions {record['review_state']['decisions']}  {record['reason']}")
        return 0
    problems = review_backup.verify_backups(REVIEW_DIR)
    for problem in problems:
        print(f"  {problem}")
    print("verify:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
