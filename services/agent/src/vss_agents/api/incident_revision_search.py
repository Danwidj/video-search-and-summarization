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

"""``POST /api/v1/incidents/revisions/search`` - incident-level search over saved report revisions.

Each saved report revision carries one summary embedding (``incident.title`` and
``incident.description``, written by ``incident_report_gen`` when the AI revision is inserted). The
route embeds the query with the same model and returns the nearest revisions by cosine similarity,
through the ``search_report_revisions`` RPC. Human revisions and AI revisions saved without an
embedding are not returned.

Status codes: 503 when the incident database or the query embedding is not available, 502 when the
embedding endpoint fails.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import Field

from vss_agents.api.incident_search import DefaultQueryEmbedder
from vss_agents.api.incident_search import EmbeddingUnavailableError
from vss_agents.api.incident_search import QueryEmbedder
from vss_agents.utils import incident_db

logger = logging.getLogger(__name__)


class RevisionSearchRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/revisions/search``."""

    query: str = Field(..., min_length=1, max_length=1000, description="Natural-language description to search for.")
    top_k: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.0, ge=-1.0, le=1.0, description="Cosine similarity floor (1.0 - distance).")


class RevisionSearchHit(BaseModel):
    """One matching report revision."""

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


def create_incident_revision_search_router(embedder: QueryEmbedder | None = None) -> APIRouter:
    """Build the ``POST /api/v1/incidents/revisions/search`` router."""
    router = APIRouter()
    # No placeholder vector: a fake query would return meaningless hits, so a missing key is a 503.
    query_embedder = embedder or DefaultQueryEmbedder(allow_placeholder=False)

    @router.post(
        "/api/v1/incidents/revisions/search",
        summary="Search saved incident report revisions by their summary embedding",
        tags=["Incident Search"],
    )
    async def search_revisions(body: RevisionSearchRequest) -> list[RevisionSearchHit]:
        db = await incident_db.get_db()
        if db is None:
            raise HTTPException(status_code=503, detail="Incident database is not configured or unreachable")
        try:
            query_embedding = await query_embedder.embed_query(body.query)
        except EmbeddingUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.error("Revision search query embedding failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail=f"Embedding endpoint failed: {exc}") from exc

        rows: list[dict[str, Any]] = await db.search_revisions(
            query_embedding, top_k=body.top_k, min_similarity=body.min_similarity
        )
        return [RevisionSearchHit.model_validate(row) for row in rows]

    return router


def register_incident_revision_search_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/revisions/search``."""
    app.include_router(create_incident_revision_search_router())
    logger.info("Registered POST /api/v1/incidents/revisions/search")
