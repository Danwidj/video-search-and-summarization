# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident search endpoint implementing search-contract-v1."""

from __future__ import annotations

import time
from typing import Any
from typing import Literal
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from base_profile_mock.finals_snapshot import evidence_hits
from base_profile_mock.finals_snapshot import match_score
from base_profile_mock.finals_snapshot import query_tokens

router = APIRouter(prefix="/api/v1")


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_types: list[str] | None = None
    min_severity: int | None = Field(default=None, ge=1, le=5)
    max_severity: int | None = Field(default=None, ge=1, le=5)
    item_types: list[Literal["entity", "instrument", "asset"]] | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    hide_rejected: bool = True
    filters: SearchFilters | None = None


# Evidence items of the finals clips (see finals_snapshot.py); the chat mock reads this list too.
_CANNED_HITS: list[dict[str, Any]] = evidence_hits()


def _searchable_text(candidate: dict[str, Any]) -> str:
    item = candidate["item"]
    incident = candidate["incident"]
    return " ".join(
        str(part or "")
        for part in (
            item["item_type"],
            item["name"],
            item["label"],
            item["description"],
            incident["incident_id"],
            incident["incident_type"],
            incident["title"],
            incident["description"],
        )
    )


@router.post("/incidents/search")
async def search_incidents(req: SearchRequest) -> dict[str, Any]:
    t0 = time.perf_counter()

    item_types = set(req.filters.item_types) if req.filters and req.filters.item_types else None
    incident_types = set(req.filters.incident_types) if req.filters and req.filters.incident_types else None
    min_sev = req.filters.min_severity if req.filters else None
    max_sev = req.filters.max_severity if req.filters else None
    tokens = query_tokens(req.query)

    matched = []
    for candidate in _CANNED_HITS:
        item = candidate["item"]
        incident = candidate["incident"]
        sim = match_score(tokens, _searchable_text(candidate))

        if sim == 0.0 or sim < req.min_similarity:
            continue
        if req.hide_rejected and candidate.get("critic", {}).get("verdict") == "rejected":
            continue
        if item_types and item["item_type"] not in item_types:
            continue
        if incident_types and incident["incident_type"] not in incident_types:
            continue
        if min_sev is not None and incident["severity_level"] < min_sev:
            continue
        if max_sev is not None and incident["severity_level"] > max_sev:
            continue

        matched.append({**candidate, "similarity_score": sim})

    # Sort descending by similarity
    matched.sort(key=lambda h: h["similarity_score"], reverse=True)
    selected = matched[: req.top_k]

    hits = []
    for idx, hit in enumerate(selected, start=1):
        hits.append(
            {
                "result_id": f"res-{uuid.uuid4().hex[:8]}",
                "rank": idx,
                "similarity_score": hit["similarity_score"],
                "item": hit["item"],
                "incident": hit["incident"],
                "critic": hit["critic"],
            }
        )

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "query_id": f"q-{uuid.uuid4().hex[:12]}",
        "query": req.query,
        "total_hits": len(hits),
        "execution_time_ms": elapsed_ms,
        "hits": hits,
    }
