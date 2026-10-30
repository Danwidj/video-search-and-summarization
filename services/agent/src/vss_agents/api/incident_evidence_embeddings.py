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


"""``POST /api/v1/incidents/evidence-embeddings`` - embeddings for an incident revision's evidence.

``incident-console-v2`` calls this when a human makes a revision official, and before it saves a
new revision that will be searchable. The body names either a stored revision (``revision_id``: the
route reads its ``evidence`` JSONB from ``report_revisions``) or the evidence items themselves
(``evidence``: nothing is read, so a revision can be embedded before it exists). Each item is embedded
as ``"{item_name}: {description}"`` passage text with the same embedding model search embeds queries
with (``RemoteTextEmbedder``, ``vector(1024)``). It returns the vectors only: the console writes
the ``evidence_crops`` rows itself. A revision can cover several videos, whose items reuse ids
(every camera has an ``E1``), so an item may name its source video (``video_id``); it is echoed back so the
caller can tell the vectors apart.

Status codes: 404 for an unknown revision, 422 when the body names neither or both sources, 503 when
the incident database or the embedding endpoint is not available, 502 when the embedding endpoint
fails.
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
from pydantic import model_validator

from vss_agents.utils import incident_db
from vss_agents.utils.embeddings import RemoteTextEmbedder

logger = logging.getLogger(__name__)


class EvidenceItemText(BaseModel):
    """One evidence item to embed when the body carries the items instead of a stored revision."""

    item_type: str
    item_id: str
    video_id: str | None = None
    item_name: str | None = None
    description: str | None = None


class EvidenceEmbeddingsRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/evidence-embeddings``: exactly one of ``revision_id`` or ``evidence``."""

    revision_id: int | None = Field(default=None, ge=1, description="report_revisions.id whose evidence is embedded.")
    evidence: list[EvidenceItemText] | None = Field(
        default=None,
        description="Evidence items to embed without reading a stored revision, so a revision can be embedded before it is saved.",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> EvidenceEmbeddingsRequest:
        if (self.revision_id is None) == (self.evidence is None):
            raise ValueError("send exactly one of revision_id or evidence")
        return self


class EvidenceEmbedding(BaseModel):
    """One evidence item's passage embedding."""

    item_type: str
    item_id: str
    video_id: str | None = None
    embedding: list[float]


def passage_text(entry: dict[str, Any]) -> str:
    """The text embedded for an evidence entry, matching how ``evidence_crops`` rows are described."""
    return f"{entry.get('item_name') or ''}: {entry.get('description') or ''}"


def create_incident_evidence_embeddings_router(embedder: RemoteTextEmbedder | None = None) -> APIRouter:
    """Build the ``POST /api/v1/incidents/evidence-embeddings`` router."""
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/evidence-embeddings",
        summary="Embed the evidence items of a report revision (used when a revision becomes official)",
        tags=["Incident Evidence"],
    )
    async def evidence_embeddings(body: EvidenceEmbeddingsRequest) -> list[EvidenceEmbedding]:
        if body.revision_id is None:
            evidence: list[Any] = [entry.model_dump() for entry in body.evidence or []]
        else:
            db = await incident_db.get_db()
            if db is None:
                raise HTTPException(status_code=503, detail="Incident database is not configured or unreachable")
            revision = await db.get_revision(body.revision_id)
            if revision is None:
                raise HTTPException(status_code=404, detail=f"Revision {body.revision_id} not found")
            evidence = revision.get("evidence") or []
        items = [
            entry for entry in evidence if isinstance(entry, dict) and entry.get("item_type") and entry.get("item_id")
        ]
        if not items:
            return []

        active_embedder = embedder or RemoteTextEmbedder()
        if not active_embedder.is_configured():
            raise HTTPException(status_code=503, detail="No embedding API key is configured")
        try:
            vectors = await active_embedder.embed([passage_text(entry) for entry in items], input_type="passage")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.error("Evidence embedding failed for revision_id=%s: %s", body.revision_id, exc, exc_info=True)
            raise HTTPException(status_code=502, detail=f"Embedding endpoint failed: {exc}") from exc
        return [
            EvidenceEmbedding(
                item_type=str(entry["item_type"]),
                item_id=str(entry["item_id"]),
                video_id=str(entry["video_id"]) if entry.get("video_id") else None,
                embedding=vector,
            )
            for entry, vector in zip(items, vectors, strict=True)
        ]

    return router


def register_incident_evidence_embeddings_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/evidence-embeddings``."""
    app.include_router(create_incident_evidence_embeddings_router())
    logger.info("Registered POST /api/v1/incidents/evidence-embeddings")
