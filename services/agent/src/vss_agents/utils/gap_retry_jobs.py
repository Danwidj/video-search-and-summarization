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

"""The chat's gap retry of one existing report: which items it looks at, and the jobs that look.

A retry takes 30 to 120 seconds an item, longer than a chat request may take, so it runs as a job: :meth:`GapRetryJobs.start`
returns at once with every item ``pending``, the job runs :meth:`CropEvidenceService.retry_report_gaps` in the background,
and the console reads the outcome back until the job is ``done``. Nothing is written to the database; a found box is only a
proposal the console puts beside the item (set image, confirmed by the reviewer).

Only one job runs per video at a time. The registry keeps the last :data:`JOBS_KEPT` jobs for reading back, in memory: a
restart of the agent forgets them, and the console then shows the retry as lost.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
import logging
import time
from typing import Any
import uuid

from vss_agents.utils import crop_evidence

logger = logging.getLogger(__name__)

JOBS_KEPT = 20
REQUEST_SECONDS = 300.0  # the time one retry may use across all its items (30 to 120 s an item, a few in parallel)
ITEM_PENDING = "pending"
ITEM_FOUND = "found"
ITEM_NOT_FOUND = "not_found"
ITEM_NOT_RETRIED = "not_retried"

Runner = Callable[[float], Awaitable[dict[str, crop_evidence.GapRetryOutcome]]]


@dataclass(frozen=True)
class Selection:
    """The items of a report to look again (``pending``: the entry and its first-look gap) and the others with the reason."""

    pending: list[tuple[dict[str, Any], str | None]]
    refused: dict[str, str]


def select(evidence: Sequence[dict[str, Any]], item_key: str | None) -> Selection:
    """Which evidence entries a retry looks at: every item with no box (or the one named), and the reason for any it cannot help.

    An item with a box is left out of a retry of all items, and reported as ``already has a box`` when it is named. Raises
    ValueError when ``item_key`` names no item of the report.
    """
    entries = [entry for entry in evidence if item_key is None or entry.get("item_id") == item_key]
    if item_key is not None and not entries:
        raise ValueError(f"there is no item {item_key} in this report")
    pending: list[tuple[dict[str, Any], str | None]] = []
    refused: dict[str, str] = {}
    for entry in entries:
        item_id = str(entry.get("item_id") or "")
        if entry.get("image") is not None:
            if item_key is not None:
                refused[item_id] = "it already has a box"
            continue
        gap = crop_evidence.stored_gap_for_retry(entry)
        if crop_evidence.gap_retry_kind(gap) is None:
            refused[item_id] = f"its first look failed in a way a retry cannot fix: {gap}"
            continue
        pending.append((entry, gap))
    return Selection(pending=pending, refused=refused)


@dataclass
class GapRetryItem:
    """One item of a job: ``found`` carries the proposed ``seconds`` and ``box``, the others a ``reason``."""

    item_id: str
    name: str
    status: str = ITEM_PENDING
    reason: str | None = None
    seconds: float | None = None
    box: list[int] | None = None


@dataclass
class GapRetryJob:
    job_id: str
    video_id: str
    revision_id: int | None
    items: list[GapRetryItem]
    done: bool = False
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class GapRetryJobs:
    """The jobs of this agent process, by id. A job runs as an asyncio task on the server's loop."""

    def __init__(self) -> None:
        self._jobs: dict[str, GapRetryJob] = {}

    def active(self, video_id: str) -> GapRetryJob | None:
        return next((job for job in self._jobs.values() if job.video_id == video_id and not job.done), None)

    def get(self, job_id: str) -> GapRetryJob | None:
        return self._jobs.get(job_id)

    def start(
        self, *, video_id: str, revision_id: int | None, selection: Selection, runner: Runner, wall_seconds: float
    ) -> GapRetryJob:
        """Record the job with its items (``pending``, or ``not_retried`` with a reason) and run ``runner`` in the background.

        ``runner`` gets the job's deadline (a ``time.monotonic()`` value, ``wall_seconds`` from now) and returns each pending
        item's outcome. Its items are updated as it returns; a failure of the runner marks the pending items as not retried.
        """
        items = [
            GapRetryItem(item_id=str(entry.get("item_id") or ""), name=str(entry.get("item_name") or ""))
            for entry, _ in selection.pending
        ]
        items += [
            GapRetryItem(item_id=item_id, name="", status=ITEM_NOT_RETRIED, reason=reason)
            for item_id, reason in selection.refused.items()
        ]
        job = GapRetryJob(job_id=uuid.uuid4().hex, video_id=video_id, revision_id=revision_id, items=items)
        self._jobs[job.job_id] = job
        self._forget_old()
        job.task = asyncio.create_task(self._run(job, runner, time.monotonic() + wall_seconds))
        return job

    async def _run(self, job: GapRetryJob, runner: Runner, deadline: float) -> None:
        try:
            outcomes = await runner(deadline)
        except Exception as exc:
            logger.warning("Gap retry for %s failed: %s", job.video_id, type(exc).__name__)
            outcomes = {}
            for item in job.items:
                if item.status == ITEM_PENDING:
                    item.status, item.reason = ITEM_NOT_RETRIED, "the retry failed"
        else:
            for item in job.items:
                if item.status != ITEM_PENDING:
                    continue
                outcome = outcomes.get(item.item_id)
                if outcome is None or outcome.found is None:
                    item.status = ITEM_NOT_FOUND
                    item.reason = outcome.reason if outcome is not None else crop_evidence.TIME_REASON
                    continue
                item.status = ITEM_FOUND
                item.seconds = outcome.found.box_seconds
                item.box = list(outcome.found.normalized_box or [])
        job.done = True

    def _forget_old(self) -> None:
        """Keep the last :data:`JOBS_KEPT` jobs: a finished one is dropped first, never a running one."""
        while len(self._jobs) > JOBS_KEPT:
            finished = next((job_id for job_id, job in self._jobs.items() if job.done), None)
            if finished is None:
                return
            del self._jobs[finished]


JOBS = GapRetryJobs()
