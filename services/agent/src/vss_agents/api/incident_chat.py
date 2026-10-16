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

"""``POST /api/v1/incidents/chat`` - Conversational Q&A over incidents and evidence crops.

Provides grounded conversational answers to user questions about surveillance incidents,
entities, instruments, and assets, accompanied by structured evidence citations
referencing exact timestamps and crop screenshots for UI inspection and jump-to-clip.

Follows a hexagonal architecture: calls evidence search capabilities through the
:class:`SearchClient` port. An in-memory adapter is provided for testing and offline
operation.

TODO(MVP2 Phase 4 / search route owner): Wire SearchClient to live search endpoint /
pgvector RPC once merged.
"""

from __future__ import annotations

import logging
from typing import Any
from typing import Protocol
from typing import runtime_checkable
import uuid

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SearchClient Port & In-Memory Adapter
# ---------------------------------------------------------------------------


@runtime_checkable
class SearchClient(Protocol):
    """Port for retrieving evidence hits matching a natural-language query."""

    async def search(
        self,
        query: str,
        top_k: int = 5,
        item_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve verified evidence hits conforming to search-contract-v1 hit shape."""
        ...


_DEFAULT_SEED_HITS: list[dict[str, Any]] = [
    {
        "result_id": "res_assault_machete",
        "rank": 1,
        "similarity_score": 0.89,
        "item": {
            "item_type": "instrument",
            "item_id": "I1",
            "name": "machete",
            "label": "machete",
            "description": "Long curved blade held by assailant during storefront altercation.",
            "threat_level": 4,
            "holder_entity_id": "E1",
            "crop_image_url": "https://pub-r2.example.com/evidence/Assault007/m86a5c319e26659804b0/instruments/I1.jpg",
            "timestamp_seconds": 14,
            "bounding_box": [320, 450, 510, 600],
        },
        "incident": {
            "incident_id": "Assault007",
            "model_run_id": "m86a5c319e26659804b0",
            "incident_type": "assault",
            "severity_level": 4,
            "title": "Physical altercation with edged weapon in ATM lobby",
            "description": "An altercation ensues where a perpetrator brandishes a large blade against a victim.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007.mp4",
            "incident_window": [10.0, 28.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.96,
            "rationale": "The cropped screenshot clearly shows a machete held in the assailant's hand.",
        },
    },
    {
        "result_id": "res_assault_perpetrator",
        "rank": 2,
        "similarity_score": 0.81,
        "item": {
            "item_type": "entity",
            "item_id": "E1",
            "name": "perpetrator",
            "label": "person",
            "description": "Adult wearing dark hooded jacket lunging toward victim.",
            "threat_level": 5,
            "holder_entity_id": None,
            "crop_image_url": "https://pub-r2.example.com/evidence/Assault007/m86a5c319e26659804b0/entities/E1.jpg",
            "timestamp_seconds": 12,
            "bounding_box": [210, 390, 820, 640],
        },
        "incident": {
            "incident_id": "Assault007",
            "model_run_id": "m86a5c319e26659804b0",
            "incident_type": "assault",
            "severity_level": 4,
            "title": "Physical altercation with edged weapon in ATM lobby",
            "description": "An altercation ensues where a perpetrator brandishes a large blade against a victim.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007.mp4",
            "incident_window": [10.0, 28.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.94,
            "rationale": "The crop depicts the primary aggressor in active motion.",
        },
    },
    {
        "result_id": "res_burglary_crowbar",
        "rank": 3,
        "similarity_score": 0.78,
        "item": {
            "item_type": "instrument",
            "item_id": "I1",
            "name": "crowbar",
            "label": "crowbar",
            "description": "Heavy metal pry bar used to force open the storefront entrance door.",
            "threat_level": 3,
            "holder_entity_id": "E1",
            "crop_image_url": "https://pub-r2.example.com/evidence/Burglary005/m41d7e220f18831902a2/instruments/I1.jpg",
            "timestamp_seconds": 8,
            "bounding_box": [400, 280, 520, 410],
        },
        "incident": {
            "incident_id": "Burglary005",
            "model_run_id": "m41d7e220f18831902a2",
            "incident_type": "burglary",
            "severity_level": 3,
            "title": "Commercial door breach after hours",
            "description": "Suspect uses a tool to lever open the security door.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/burglary/Burglary005.mp4",
            "incident_window": [5.0, 20.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.92,
            "rationale": "The crop clearly shows a metal pry bar engaged with the door frame.",
        },
    },
    {
        "result_id": "res_burglary_safe",
        "rank": 4,
        "similarity_score": 0.72,
        "item": {
            "item_type": "asset",
            "item_id": "A1",
            "name": "cash safe",
            "label": "safe",
            "description": "Anchored metal safe box targeted by intruder.",
            "threat_level": None,
            "holder_entity_id": None,
            "crop_image_url": "https://pub-r2.example.com/evidence/Burglary005/m41d7e220f18831902a2/assets/A1.jpg",
            "timestamp_seconds": 15,
            "bounding_box": [500, 600, 750, 850],
        },
        "incident": {
            "incident_id": "Burglary005",
            "model_run_id": "m41d7e220f18831902a2",
            "incident_type": "burglary",
            "severity_level": 3,
            "title": "Commercial door breach after hours",
            "description": "Suspect uses a tool to lever open the security door.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/burglary/Burglary005.mp4",
            "incident_window": [5.0, 20.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.90,
            "rationale": "The crop displays the targeted commercial safe fixture.",
        },
    },
]


class InMemorySearchClient:
    """In-memory SearchClient adapter for testing, mocks, and local development."""

    def __init__(self, seed_hits: list[dict[str, Any]] | None = None) -> None:
        self.hits = list(seed_hits if seed_hits is not None else _DEFAULT_SEED_HITS)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        item_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower().strip()
        query_tokens = [tok for tok in query_lower.replace("?", " ").replace(",", " ").split() if len(tok) > 2]

        incident_id_filter = filters.get("incident_id") if filters else None
        incident_types_filter = filters.get("incident_types") if filters else None

        matched_hits: list[tuple[float, dict[str, Any]]] = []
        for hit in self.hits:
            item = hit.get("item", {})
            incident = hit.get("incident", {})

            # Filter by incident_id if specified
            if incident_id_filter and incident.get("incident_id") != incident_id_filter:
                continue

            # Filter by item_type if specified
            if item_types and item.get("item_type") not in item_types:
                continue

            # Filter by incident_types if specified
            if incident_types_filter and incident.get("incident_type") not in incident_types_filter:
                continue

            # Keyword matching against searchable text fields
            searchable_text = " ".join(
                [
                    str(item.get("item_type", "")),
                    str(item.get("name", "")),
                    str(item.get("label", "")),
                    str(item.get("description", "")),
                    str(incident.get("incident_id", "")),
                    str(incident.get("title", "")),
                    str(incident.get("incident_type", "")),
                    str(incident.get("description", "")),
                ]
            ).lower()

            # If query has tokens, at least one token should match; if query has no tokens, match all
            if query_tokens:
                score = sum(
                    1
                    for tok in query_tokens
                    if tok in searchable_text or (len(tok) > 3 and tok.rstrip("s") in searchable_text)
                )
                if score > 0:
                    matched_hits.append((score, hit))
                elif incident_id_filter:
                    matched_hits.append((0.1, hit))
            else:
                matched_hits.append((1, hit))

        # Sort by match score descending
        matched_hits.sort(key=lambda pair: pair[0], reverse=True)
        return [hit for _, hit in matched_hits[:top_k]]


# ---------------------------------------------------------------------------
# Request & Response Data Models (chat-contract-v1)
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of message author ('user', 'assistant', 'system')")
    content: str = Field(..., min_length=1, description="Text content of message")


class ChatContext(BaseModel):
    scope: str = Field(default="global", description="Scope of conversation: 'global' or 'incident'")
    incident_id: str | None = Field(default=None, description="Optional incident_id when scope is 'incident'")
    evidence_crop_ids: list[str] | None = Field(default=None, description="Optional evidence item IDs")


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=128, description="Optional session ID")
    messages: list[ChatMessage] = Field(..., min_length=1, description="Message history")
    context: ChatContext | None = Field(default=None, description="Optional context")


class EvidenceCitation(BaseModel):
    incident_id: str
    item_id: str
    item_type: str
    timestamp_seconds: float
    crop_image_url: str


class AssistantMessage(BaseModel):
    role: str = "assistant"
    content: str
    citations: list[EvidenceCitation] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    message: AssistantMessage


# ---------------------------------------------------------------------------
# Router & Registration
# ---------------------------------------------------------------------------


def create_incident_chat_router(search_client: SearchClient | None = None) -> APIRouter:
    """Build the ``POST /api/v1/incidents/chat`` router with an injected or default SearchClient."""
    router = APIRouter()
    client: SearchClient = search_client if search_client is not None else InMemorySearchClient()

    @router.post(
        "/api/v1/incidents/chat",
        response_model=ChatResponse,
        summary="Conversational Q&A over incidents and evidence crops with grounded citations",
        tags=["Incident Chat"],
    )
    async def chat_incidents(body: ChatRequest) -> ChatResponse:
        session_id = body.session_id or f"session_{uuid.uuid4().hex[:12]}"

        # Validate context scope
        if body.context and body.context.scope not in ("global", "incident"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid scope '{body.context.scope}'; must be 'global' or 'incident'",
            )

        # Extract latest user message
        user_message: ChatMessage | None = None
        for msg in reversed(body.messages):
            if msg.role == "user":
                user_message = msg
                break

        if not user_message:
            raise HTTPException(status_code=400, detail="At least one message with role 'user' is required")

        query_text = user_message.content.strip()
        if not query_text:
            raise HTTPException(status_code=400, detail="User message content must not be empty")

        # Prepare search filters
        filters: dict[str, Any] = {}
        if body.context and body.context.scope == "incident" and body.context.incident_id:
            filters["incident_id"] = body.context.incident_id

        # Query evidence search through the SearchClient port
        try:
            hits = await client.search(
                query=query_text,
                top_k=5,
                filters=filters,
            )
        except Exception as exc:
            logger.error("SearchClient failed during incident chat: %s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail=f"Evidence search error: {exc}") from exc

        # Handle empty results cleanly
        if not hits:
            scope_desc = (
                f" in incident {body.context.incident_id}"
                if body.context and body.context.scope == "incident" and body.context.incident_id
                else ""
            )
            return ChatResponse(
                session_id=session_id,
                message=AssistantMessage(
                    role="assistant",
                    content=f"No matching incidents or evidence items were found for '{query_text}'{scope_desc}.",
                    citations=[],
                ),
            )

        # Ground answer with citations
        citations: list[EvidenceCitation] = []
        seen_items: set[tuple[str, str]] = set()
        item_summaries: list[str] = []

        for hit in hits:
            item = hit.get("item", {})
            incident = hit.get("incident", {})
            inc_id = incident.get("incident_id", "unknown")
            item_id = item.get("item_id", "unknown")
            item_type = item.get("item_type", "entity")
            ts = float(item.get("timestamp_seconds", 0.0))
            crop_url = item.get("crop_image_url", "")

            key = (inc_id, item_id)
            if key not in seen_items:
                seen_items.add(key)
                citations.append(
                    EvidenceCitation(
                        incident_id=inc_id,
                        item_id=item_id,
                        item_type=item_type,
                        timestamp_seconds=ts,
                        crop_image_url=crop_url,
                    )
                )
                item_name = item.get("name") or item.get("label") or item_id
                inc_type = incident.get("incident_type", "incident")
                item_summaries.append(f"{item_name} ({item_id}) in {inc_id} ({inc_type} at {int(ts)}s)")

        summary_text = "; ".join(item_summaries)
        content = (
            f"Based on the surveillance evidence, {len(citations)} relevant item(s) were identified: {summary_text}."
        )

        return ChatResponse(
            session_id=session_id,
            message=AssistantMessage(
                role="assistant",
                content=content,
                citations=citations,
            ),
        )

    return router


def register_incident_chat_routes(app: FastAPI, search_client: SearchClient | None = None) -> None:
    """Register ``POST /api/v1/incidents/chat`` onto the FastAPI app."""
    try:
        app.include_router(create_incident_chat_router(search_client))
        logger.info("Registered POST /api/v1/incidents/chat")
    except Exception as exc:
        logger.error("Failed to register incident chat routes: %s", exc, exc_info=True)
        raise
