# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident-level revision search, shaped like the agent's RevisionSearchHit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic import Field

router = APIRouter(prefix="/api/v1")


class RevisionSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.0, ge=-1.0, le=1.0)


class RevisionSearchHit(BaseModel):
    revision_id: int
    video_id: str
    revision_no: int
    kind: str
    model_run_id: str | None
    title: str | None
    description: str | None
    incident_type: str | None
    severity_level: int | None
    start_seconds: int | None
    end_seconds: int | None
    similarity_score: float


_CANNED_REVISIONS: list[dict[str, Any]] = [
    {
        "revision_id": 101,
        "video_id": "Assault007_x264",
        "revision_no": 2,
        "kind": "ai",
        "model_run_id": "m86a5c319e26659804b0",
        "title": "Physical altercation with edged weapon in ATM lobby",
        "description": "A perpetrator brandishes a large blade against a victim inside an ATM lobby.",
        "incident_type": "assault",
        "severity_level": 4,
        "start_seconds": 10,
        "end_seconds": 28,
        "similarity_score": 0.89,
    },
    {
        "revision_id": 102,
        "video_id": "Burglary004_x264",
        "revision_no": 1,
        "kind": "ai",
        "model_run_id": "m5d1c0e7a93b24f6c8e1",
        "title": "Forced entry through a rear storefront door",
        "description": "Two people pry open a rear door at night and carry out boxed goods.",
        "incident_type": "burglary",
        "severity_level": 3,
        "start_seconds": 6,
        "end_seconds": 41,
        "similarity_score": 0.74,
    },
    {
        "revision_id": 103,
        "video_id": "Robbery012_x264",
        "revision_no": 3,
        "kind": "ai",
        "model_run_id": "m0c7be41d52a98f3a60",
        "title": "Armed robbery of a convenience store clerk",
        "description": "A masked person points a handgun at the clerk and takes cash from the register.",
        "incident_type": "robbery",
        "severity_level": 5,
        "start_seconds": 3,
        "end_seconds": 22,
        "similarity_score": 0.61,
    },
]


@router.post(
    "/incidents/revisions/search",
    response_model=list[RevisionSearchHit],
    summary="Mock search over saved incident report revisions",
    tags=["Incident Search"],
)
async def search_revisions(req: RevisionSearchRequest) -> list[dict[str, Any]]:
    matched = [r for r in _CANNED_REVISIONS if r["similarity_score"] >= req.min_similarity]
    matched.sort(key=lambda r: r["similarity_score"], reverse=True)
    return matched[: req.top_k]
