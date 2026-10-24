# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident-level revision search, shaped like the agent's RevisionSearchHit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic import Field

from base_profile_mock.finals_snapshot import match_score
from base_profile_mock.finals_snapshot import query_tokens
from base_profile_mock.finals_snapshot import revision_hits

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


# One hit per finals AI revision (see finals_snapshot.py).
_CANNED_REVISIONS: list[dict[str, Any]] = revision_hits()


@router.post(
    "/incidents/revisions/search",
    response_model=list[RevisionSearchHit],
    summary="Mock search over saved incident report revisions",
    tags=["Incident Search"],
)
async def search_revisions(req: RevisionSearchRequest) -> list[dict[str, Any]]:
    tokens = query_tokens(req.query)
    scored = []
    for rev in _CANNED_REVISIONS:
        text = " ".join(str(rev[key] or "") for key in ("title", "description", "incident_type", "video_id"))
        sim = match_score(tokens, text)
        if sim == 0.0 or sim < req.min_similarity:
            continue
        scored.append({**rev, "similarity_score": sim})
    scored.sort(key=lambda r: r["similarity_score"], reverse=True)
    return scored[: req.top_k]
