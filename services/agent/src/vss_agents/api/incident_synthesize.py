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

"""``POST /api/v1/incidents/synthesize`` - stateless multi-video incident overview.

Given one or more ``{video_name, payload}`` pairs (each ``payload`` is a contract-valid analysis
from P1/``/analyze``) it returns:

- ``overview`` - the ``incident`` block fields of ``incident-contract-v4``, synthesised across all
  videos.  For exactly one video the overview is the video's own ``incident`` block unchanged.
- ``embedding`` - a ``vector(1024)`` search embedding of the overview text (``title`` + ``description``).

The endpoint is **stateless**: it writes nothing to the database and never alters the per-video
payloads.  The caller (``incident-console-v2``) stores the result.

Status codes:
- 422  body validation failed (empty ``videos`` list, payload not contract-valid).
- 503  embedding API key or RP1 endpoint not configured / unreachable.
- 502  LLM synthesis call or embedding call returned an error.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from vss_agents import incident_contract
from vss_agents.utils.embeddings import RemoteTextEmbedder

logger = logging.getLogger(__name__)

# Overview fields are a strict subset of ContractIncident fields.
_OVERVIEW_FIELDS = frozenset(
    {
        "type",
        "title",
        "start_timestamp",
        "end_timestamp",
        "description",
        "severity_level",
        "severity_reason",
        "confidence_score",
        "location",
    }
)

_SYNTHESIS_PROMPT_TEMPLATE = """\
You are an incident analyst. Multiple security cameras recorded the same incident from different angles or at different times.
Below are the structured incident analyses, one per camera. Synthesise them into a single overview that best describes the incident as a whole.

CAMERA ANALYSES:
{analyses}

Return a JSON object with exactly these fields (same types and constraints as the incident-contract-v4 "incident" block):
- "type": one of "road accident", "burglary", "explosion", "assault", "animal attack"
- "title": short neutral headline, 4-10 words
- "start_timestamp": integer seconds >= 0 (earliest across cameras)
- "end_timestamp": integer seconds >= 0 (latest across cameras, >= start_timestamp)
- "description": short objective description, 1-3 sentences, covering all cameras
- "severity_level": integer 1-5 (highest across cameras)
- "severity_reason": observable evidence for the severity_level
- "confidence_score": number 0-1 or null
- "location": visible setting string or null

Return ONLY the JSON object, no markdown fences or extra text."""


class VideoAnalysisInput(BaseModel):
    """One video's name and its contract-valid analysis payload."""

    video_name: str = Field(..., min_length=1, max_length=900)
    payload: dict[str, Any] = Field(..., description="Contract-valid analysis payload from /analyze.")

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        try:
            incident_contract.validate_report(v)
        except incident_contract.IncidentExtractionError as exc:
            raise ValueError(f"payload is not contract-valid: {exc}") from exc
        return v


class SynthesizeRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/synthesize``."""

    videos: list[VideoAnalysisInput] = Field(..., min_length=1, description="At least one video analysis.")


class SynthesizeResponse(BaseModel):
    """Response for ``POST /api/v1/incidents/synthesize``."""

    overview: dict[str, Any] = Field(
        description="Synthesised incident overview (incident-contract-v4 incident fields)."
    )
    embedding: list[float] = Field(description="Search embedding of the overview text (1024 dimensions).")


def _overview_from_incident(incident: dict[str, Any]) -> dict[str, Any]:
    """Extract and return only the overview fields from an incident block."""
    return {k: v for k, v in incident.items() if k in _OVERVIEW_FIELDS}


def _overview_text(overview: dict[str, Any]) -> str:
    """Text used for the search embedding."""
    parts = [overview.get("title") or "", overview.get("description") or ""]
    return " ".join(p for p in parts if p).strip()


async def _synthesise_via_llm(
    videos: list[VideoAnalysisInput],
    rp1_base_url: str,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    """Call the LLM to merge multiple video analyses into one overview."""
    analyses_text = "\n\n".join(
        f"Camera: {v.video_name}\n{json.dumps(v.payload.get('incident', {}), indent=2)}" for v in videos
    )
    prompt = _SYNTHESIS_PROMPT_TEMPLATE.format(analyses=analyses_text)
    rp1_settings = incident_contract.rp1_request()
    model = rp1_settings.pop("model")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        **rp1_settings,
    }
    url = f"{rp1_base_url.rstrip('/')}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"})
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"Synthesis LLM returned HTTP {response.status_code}: {response.text[:300]}",
            request=response.request,
            response=response,
        )
    choices = response.json().get("choices") or []
    if not choices:
        raise ValueError("Synthesis LLM returned no choices")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("Synthesis LLM returned empty content")
    try:
        overview = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Synthesis LLM returned non-JSON: {content[:200]}") from exc
    # Keep only the expected fields and validate the type field is valid.
    filtered: dict[str, Any] = {k: v for k, v in overview.items() if k in _OVERVIEW_FIELDS}
    # Ensure end_timestamp >= start_timestamp.
    start = filtered.get("start_timestamp")
    end = filtered.get("end_timestamp")
    if isinstance(start, int) and isinstance(end, int) and end < start:
        filtered["end_timestamp"] = start
    return filtered


def create_incident_synthesize_router(
    embedder: RemoteTextEmbedder | None = None,
    rp1_base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> APIRouter:
    """Build the ``POST /api/v1/incidents/synthesize`` router."""
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/synthesize",
        summary="Synthesise a multi-video incident overview and search embedding (stateless)",
        tags=["Incident Synthesize"],
    )
    async def synthesize_incident(body: SynthesizeRequest) -> SynthesizeResponse:
        # For exactly one video pass through the incident block directly.
        if len(body.videos) == 1:
            incident_block = body.videos[0].payload.get("incident") or {}
            overview = _overview_from_incident(incident_block)
        else:
            if not rp1_base_url:
                raise HTTPException(status_code=503, detail="rp1_base_url is not configured on this agent")
            effective_key = api_key or ""
            if not effective_key:
                raise HTTPException(status_code=503, detail="No API key configured for LLM synthesis")
            try:
                overview = await _synthesise_via_llm(body.videos, rp1_base_url, effective_key, timeout)
            except httpx.HTTPStatusError as exc:
                logger.error("Synthesis LLM request failed: %s", exc)
                raise HTTPException(status_code=502, detail=f"Synthesis LLM failed: {exc}") from exc
            except Exception as exc:
                logger.error("Synthesis failed: %s", exc, exc_info=True)
                raise HTTPException(status_code=502, detail=f"Synthesis failed: {exc}") from exc

        text = _overview_text(overview)
        active_embedder = embedder or RemoteTextEmbedder()
        if not active_embedder.is_configured():
            raise HTTPException(status_code=503, detail="No embedding API key configured")
        try:
            embedding = await active_embedder.embed_passage(text)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.error("Embedding failed during synthesis: %s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail=f"Embedding failed: {exc}") from exc

        return SynthesizeResponse(overview=overview, embedding=embedding)

    return router


def register_incident_synthesize_routes(
    app: FastAPI,
    rp1_base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> None:
    """Register ``POST /api/v1/incidents/synthesize``."""
    app.include_router(create_incident_synthesize_router(rp1_base_url=rp1_base_url, api_key=api_key, timeout=timeout))
    logger.info("Registered POST /api/v1/incidents/synthesize")
