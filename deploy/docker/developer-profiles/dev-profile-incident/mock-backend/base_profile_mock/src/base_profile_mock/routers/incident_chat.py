# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident chat endpoint implementing chat-contract-v1."""

from __future__ import annotations

import logging
from typing import Any
from typing import Literal
import uuid

from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from base_profile_mock.routers.incident_search import _CANNED_HITS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="Role of message author ('user', 'assistant', 'system')"
    )
    content: str = Field(..., min_length=1, description="Message text content")


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["global", "incident"] = Field(
        default="global", description="Scope of conversation: 'global' or 'incident'"
    )
    incident_id: str | None = Field(default=None, description="Optional incident_id for incident scope")
    evidence_crop_ids: list[str] | None = Field(default=None, description="Optional evidence item IDs")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, min_length=1, max_length=128, description="Optional session ID")
    messages: list[ChatMessage] = Field(..., min_length=1, description="Sequential message history")
    context: ChatContext | None = Field(default=None, description="Optional context")


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    item_type: Literal["entity", "instrument", "asset"]
    timestamp_seconds: float = Field(..., ge=0)
    crop_image_url: str


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"] = "assistant"
    content: str
    citations: list[EvidenceCitation]


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1)
    message: AssistantMessage


@router.post(
    "/incidents/chat",
    response_model=ChatResponse,
    summary="Mock conversational Q&A over incidents and evidence crops with grounded citations",
    tags=["Incident Chat"],
)
async def chat_incidents(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or f"session_{uuid.uuid4().hex[:12]}"

    # Extract latest user message
    user_msg: ChatMessage | None = None
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_msg = msg
            break

    if not user_msg:
        raise HTTPException(status_code=400, detail="At least one message with role 'user' is required")

    query_text = user_msg.content.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="User message content must not be empty")

    query_lower = query_text.lower()
    query_tokens = [tok for tok in query_lower.replace("?", " ").replace(",", " ").split() if len(tok) > 2]

    target_incident_id = req.context.incident_id if req.context and req.context.scope == "incident" else None

    matched_hits: list[tuple[float, dict[str, Any]]] = []
    for hit in _CANNED_HITS:
        item = hit.get("item", {})
        incident = hit.get("incident", {})
        inc_id = str(incident.get("incident_id", ""))

        if (
            target_incident_id
            and target_incident_id != inc_id
            and target_incident_id not in inc_id
            and inc_id not in target_incident_id
        ):
            continue

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

        if query_tokens:
            score = sum(
                1
                for tok in query_tokens
                if tok in searchable_text or (len(tok) > 3 and tok.rstrip("s") in searchable_text)
            )
            if score > 0:
                matched_hits.append((score, hit))
            elif target_incident_id:
                matched_hits.append((0.1, hit))
        else:
            matched_hits.append((1, hit))

    matched_hits.sort(key=lambda pair: pair[0], reverse=True)
    selected_hits = [hit for _, hit in matched_hits[:5]]

    if not selected_hits:
        scope_note = f" in incident {target_incident_id}" if target_incident_id else ""
        return ChatResponse(
            session_id=session_id,
            message=AssistantMessage(
                role="assistant",
                content=f"No matching incidents or evidence items were found for '{query_text}'{scope_note}.",
                citations=[],
            ),
        )

    citations: list[EvidenceCitation] = []
    seen_items: set[tuple[str, str]] = set()
    item_summaries: list[str] = []

    for hit in selected_hits:
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
        f"Across the recorded surveillance incidents, {len(citations)} relevant evidence item(s) were identified: "
        f"{summary_text}."
    )

    return ChatResponse(
        session_id=session_id,
        message=AssistantMessage(
            role="assistant",
            content=content,
            citations=citations,
        ),
    )
