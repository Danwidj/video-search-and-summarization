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

"""The chat's gap retry of one existing report: a job that looks again for the items with no box.

- ``POST /api/v1/incidents/{video_id}/gap-retries`` starts the job for the report's newest version (or ``revision_id``, or
  the official one when neither is given) and returns ``202`` with every item. ``item_key`` limits it to one item; left out,
  every item with no box is looked at. The report editor's ``propose_retry_gaps`` tool asks for it through the console.
- ``GET /api/v1/incidents/{video_id}/gap-retries/{job_id}`` returns the job: ``running`` or ``done``, each item ``pending``,
  ``found`` (a ``seconds`` and ``box`` the console proposes beside the item), ``not_found`` or ``not_retried``, with a reason.

Nothing is written. Status codes: 404 for an unknown video, report or job, 409 when a retry of this video is already
running, 422 for an ``item_key`` the report does not have, 503 when the incident database is not configured.
See :mod:`vss_agents.utils.gap_retry_jobs` and :meth:`vss_agents.utils.crop_evidence.CropEvidenceService.retry_report_gaps`.
"""

from __future__ import annotations

import logging
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.utils import crop_evidence
from vss_agents.utils import gap_retry_jobs
from vss_agents.utils import incident_db
from vss_agents.utils.r2 import resolve_r2_url

logger = logging.getLogger(__name__)


class GapRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str | None = Field(None, min_length=1, max_length=128)
    revision_id: int | None = Field(None, ge=1)


class GapRetryItemOut(BaseModel):
    item_key: str
    name: str
    status: Literal["pending", "found", "not_found", "not_retried"]
    reason: str | None = None
    seconds: float | None = None
    box: list[int] | None = Field(None, description="[ymin, xmin, ymax, xmax], 0-1000, of the proposed crop")


class GapRetryJobOut(BaseModel):
    job_id: str
    video_id: str
    revision_id: int | None
    status: Literal["running", "done"]
    items: list[GapRetryItemOut]


def _job_out(job: gap_retry_jobs.GapRetryJob) -> GapRetryJobOut:
    return GapRetryJobOut(
        job_id=job.job_id,
        video_id=job.video_id,
        revision_id=job.revision_id,
        status="done" if job.done else "running",
        items=[
            GapRetryItemOut(
                item_key=item.item_id,
                name=item.name,
                status=item.status,  # type: ignore[arg-type]
                reason=item.reason,
                seconds=item.seconds,
                box=item.box,
            )
            for item in job.items
        ],
    )


async def _report_revision(
    db: incident_db.IncidentDB, video_id: str, video: dict[str, Any], revision_id: int | None
) -> dict[str, Any] | None:
    """The revision to look at: ``revision_id`` (of this video), else the official one, else the newest."""
    if revision_id is not None:
        revision = await db.get_revision(revision_id)
        return revision if revision is not None and revision.get("video_id") == video_id else None
    official = video.get("official_revision_id")
    if official is not None:
        revision = await db.get_revision(int(official))
        if revision is not None:
            return revision
    revisions = await db.list_revisions(video_id)
    return revisions[-1] if revisions else None


def create_incident_gap_retry_router(jobs: gap_retry_jobs.GapRetryJobs = gap_retry_jobs.JOBS) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/{video_id}/gap-retries",
        status_code=202,
        response_model=GapRetryJobOut,
        summary="Look again for the items of a report that have no box; writes nothing",
        tags=["Incident Chat"],
    )
    async def start_gap_retry(video_id: str, body: GapRetryRequest) -> GapRetryJobOut:
        db = await incident_db.get_db()
        if db is None:
            raise HTTPException(status_code=503, detail="The incident database is not configured")
        video = await db.get_video(video_id)
        if video is None:
            raise HTTPException(status_code=404, detail=f"There is no video {video_id}")
        if jobs.active(video_id) is not None:
            raise HTTPException(status_code=409, detail="A gap retry for this report is already running")
        revision = await _report_revision(db, video_id, video, body.revision_id)
        if revision is None:
            raise HTTPException(status_code=404, detail="This video has no report to retry")
        filepath = str(video.get("filepath") or "").strip()
        if not filepath:
            raise HTTPException(status_code=404, detail="This video has no stored file to look in")
        try:
            selection = gap_retry_jobs.select(revision.get("evidence") or [], body.item_key)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        video_ref = resolve_r2_url(filepath)
        service = crop_evidence.get_crop_evidence_service()

        async def run(deadline: float) -> dict[str, crop_evidence.GapRetryOutcome]:
            return await service.retry_report_gaps(
                video_ref=video_ref, video_id=video_id, pending=selection.pending, deadline=deadline
            )

        job = jobs.start(
            video_id=video_id,
            revision_id=revision.get("id"),
            selection=selection,
            runner=run,
            wall_seconds=gap_retry_jobs.REQUEST_SECONDS,
        )
        logger.info("Gap retry %s for %s: %d items to look at", job.job_id, video_id, len(selection.pending))
        return _job_out(job)

    @router.get(
        "/api/v1/incidents/{video_id}/gap-retries/{job_id}",
        response_model=GapRetryJobOut,
        summary="Read a gap retry: its items as they stand, and whether it is done",
        tags=["Incident Chat"],
    )
    async def read_gap_retry(video_id: str, job_id: str) -> GapRetryJobOut:
        job = jobs.get(job_id)
        if job is None or job.video_id != video_id:
            raise HTTPException(status_code=404, detail="There is no such gap retry")
        return _job_out(job)

    return router


def register_incident_gap_retry_routes(app: FastAPI) -> None:
    """Register the gap retry routes onto the FastAPI app."""
    app.include_router(create_incident_gap_retry_router())
    logger.info("Registered POST and GET /api/v1/incidents/{video_id}/gap-retries")
