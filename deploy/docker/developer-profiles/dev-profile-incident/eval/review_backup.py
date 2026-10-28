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

"""Safeguards and versioned local backups for the ground-truth review workbook.

Review decisions live only in the working workbook (``Change Log`` status, reviewer and
notes), so the workbook must never be overwritten by a rebuild without a warning, and every
reviewed state should be recoverable:

- ``review_state`` reads a workbook's decisions: status counts and how many entries have a
  reviewer or notes.
- ``guard_overwrite`` is called before a rebuild writes over an existing workbook. It refuses
  unless overwriting is explicitly requested, refuses even then when the workbook holds review
  decisions (unless discarding them is requested too), and refuses while Excel has it open.
- ``backup`` copies the workbook to ``backups/<name> <UTC time> <sha8>.xlsx``, never
  overwriting a backup, and appends a line to ``backups/backup-log.jsonl`` with the SHA-256,
  size and review state. A permitted overwrite always takes a backup first.

All local: nothing here writes to R2 or any other shared storage.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

STATUS_COLUMN, REVIEWER_COLUMN, NOTES_COLUMN = 16, 17, 18
BACKUP_DIR_NAME = "backups"
BACKUP_LOG = "backup-log.jsonl"
# Set by a build, not by a person (AI-* = AI-assisted adjudication, never a human decision).
MACHINE_STATUSES = ("Pending", "Auto-verified", "Informational", "AI-Accepted", "AI-Rejected", "AI-Modified",
                    "AI-Unresolved")


class OverwriteRefusedError(RuntimeError):
    """A rebuild would overwrite an existing review workbook without the required confirmation."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def review_state(path: Path) -> dict:
    """``{"entries", "statuses", "with_reviewer", "with_notes", "decisions"}`` of a review workbook.

    ``decisions`` counts entries a person has touched: a status other than Pending (or the
    machine-set ``Auto-verified`` of a candidate workbook), a reviewer or notes.
    """
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Change Log" not in workbook.sheetnames:
        return {"entries": 0, "statuses": {}, "with_reviewer": 0, "with_notes": 0, "decisions": 0}
    statuses: Counter = Counter()
    with_reviewer = with_notes = decisions = entries = 0
    for row in workbook["Change Log"].iter_rows(min_row=2, values_only=True):
        if not row or row[0] in (None, ""):
            continue
        entries += 1
        status = str(row[STATUS_COLUMN - 1] or "").strip() or "(blank)"
        reviewer = str(row[REVIEWER_COLUMN - 1] or "").strip() if len(row) >= REVIEWER_COLUMN else ""
        notes = str(row[NOTES_COLUMN - 1] or "").strip() if len(row) >= NOTES_COLUMN else ""
        statuses[status] += 1
        with_reviewer += bool(reviewer)
        with_notes += bool(notes)
        decisions += status not in MACHINE_STATUSES or bool(reviewer) or bool(notes)
    workbook.close()
    return {"entries": entries, "statuses": dict(sorted(statuses.items())), "with_reviewer": with_reviewer,
            "with_notes": with_notes, "decisions": decisions}


def lock_file(path: Path) -> Path:
    """Excel's owner file for an open workbook (``~$`` plus the name)."""
    return path.with_name("~$" + path.name)


def guard_overwrite(path: Path, *, overwrite: bool, discard_review_decisions: bool) -> dict | None:
    """Refuse to write over ``path`` unless it is safe and explicitly requested; returns its review state."""
    if not path.exists():
        return None
    if lock_file(path).exists():
        raise OverwriteRefusedError(f"{path.name} is open in Excel ({lock_file(path).name} exists); close it first")
    state = review_state(path)
    if state["decisions"] and not discard_review_decisions:
        raise OverwriteRefusedError(
            f"{path.name} holds {state['decisions']} review decision(s) {state['statuses']}; rebuilding would discard "
            "them. Build a new version (--version) instead, or pass --overwrite --discard-review-decisions "
            "(a backup is taken first)")
    if not overwrite:
        raise OverwriteRefusedError(
            f"{path.name} already exists; pass --overwrite to replace it (a backup is taken first), or build a new "
            "version with --version")
    return state


def backup(path: Path, *, reason: str, now: datetime | None = None) -> dict:
    """Copy ``path`` to an immutable, timestamped backup and log it; returns the log record."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    sha = sha256_file(path)
    backups = path.parent / BACKUP_DIR_NAME
    backups.mkdir(exist_ok=True)
    target = backups / f"{path.stem} {stamp} {sha[:8]}{path.suffix}"
    suffix = 1
    while target.exists():  # never overwrite a backup, even within the same second
        suffix += 1
        target = backups / f"{path.stem} {stamp} {sha[:8]} ({suffix}){path.suffix}"
    shutil.copy2(path, target)
    if sha256_file(target) != sha:
        target.unlink()
        raise OSError(f"backup of {path.name} did not verify")
    record = {"time": stamp, "source": path.name, "backup": target.name, "sha256": sha,
              "size_bytes": target.stat().st_size, "reason": reason, "review_state": review_state(path)}
    with (backups / BACKUP_LOG).open("a") as log:
        log.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def verify_backups(review_dir: Path) -> list[str]:
    """Problems with the backups listed in the log (missing file or changed content); empty when all verify."""
    log_path = review_dir / BACKUP_DIR_NAME / BACKUP_LOG
    if not log_path.exists():
        return []
    problems = []
    for line in log_path.read_text().splitlines():
        record = json.loads(line)
        target = review_dir / BACKUP_DIR_NAME / record["backup"]
        if not target.exists():
            problems.append(f"{record['backup']}: missing")
        elif sha256_file(target) != record["sha256"]:
            problems.append(f"{record['backup']}: content changed")
    return problems
