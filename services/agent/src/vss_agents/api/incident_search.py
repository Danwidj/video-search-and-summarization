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

"""Incident search endpoint implementing search-contract-v1 with an always-on critic."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
import asyncio
import datetime as _dt
import json
import logging
import os
import time
from typing import Any
from typing import Literal
import uuid

from fastapi import APIRouter
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from vss_agents.utils import incident_db
from vss_agents.utils.r2 import resolve_r2_url

logger = logging.getLogger(__name__)

DEFAULT_VLM_BASE_URL = "https://switchyard-13doh4lsz.brevlab.com"
DEFAULT_VLM_MODEL = "nvidia/cosmos-3-super-reasoner"
DEFAULT_CRITIC_TIMEOUT_SECONDS = 30.0
DEFAULT_CRITIC_DELAY_SECONDS = 1.0
CRITIC_DELAY_ENV_VAR = "INCIDENT_SEARCH_CRITIC_DELAY_SECONDS"


def _get_critic_delay_seconds(configured_delay: float | None = None) -> float:
    """Resolve the delay between critic calls in seconds.

    Checks configured_delay first, then INCIDENT_SEARCH_CRITIC_DELAY_SECONDS environment variable,
    falling back to DEFAULT_CRITIC_DELAY_SECONDS (1.0s). 0 disables the delay.
    """
    if configured_delay is not None:
        return max(0.0, float(configured_delay))
    raw = os.getenv(CRITIC_DELAY_ENV_VAR)
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            logger.warning(
                "Invalid %s=%r; falling back to default %s",
                CRITIC_DELAY_ENV_VAR,
                raw,
                DEFAULT_CRITIC_DELAY_SECONDS,
            )
    return DEFAULT_CRITIC_DELAY_SECONDS


# =============================================================================
# Request & Response Contracts (search-contract-v1)
# =============================================================================


class SearchFilters(BaseModel):
    """Optional search filters matching search-contract-v1 search_request.schema.json."""

    model_config = ConfigDict(extra="forbid")

    incident_types: list[str] | None = None
    min_severity: int | None = Field(default=None, ge=1, le=5)
    max_severity: int | None = Field(default=None, ge=1, le=5)
    item_types: list[Literal["entity", "instrument", "asset"]] | None = None


class SearchRequest(BaseModel):
    """Request body for POST /api/v1/incidents/search matching search-contract-v1."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.2, ge=0.0, le=1.0)
    filters: SearchFilters | None = None


class CriticVerdict(BaseModel):
    """Always-on VLM critic evaluation verdict matching search-contract-v1."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["confirmed", "rejected", "unverified"]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str


class ItemHit(BaseModel):
    """Item category and visual evidence details matching search-contract-v1."""

    model_config = ConfigDict(extra="forbid")

    item_type: Literal["entity", "instrument", "asset"]
    item_id: str
    name: str
    label: str
    description: str
    threat_level: int | None = None
    holder_entity_id: str | None = None
    crop_image_url: str
    timestamp_seconds: int = Field(..., ge=0)
    bounding_box: list[int] | None = None

    @field_validator("bounding_box")
    @classmethod
    def check_bbox_length(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and len(v) != 4:
            raise ValueError("bounding_box must contain exactly 4 normalized integers [ymin, xmin, ymax, xmax]")
        return v


class IncidentHit(BaseModel):
    """Parent incident metadata matching search-contract-v1."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    model_run_id: str
    incident_type: str
    severity_level: int = Field(..., ge=1, le=5)
    title: str | None = None
    description: str
    playback_url: str
    incident_window: list[float] = Field(..., min_length=2, max_length=2)


class SearchHit(BaseModel):
    """A ranked search result with item details, incident metadata, and critic verdict."""

    model_config = ConfigDict(extra="forbid")

    result_id: str
    rank: int = Field(..., ge=1)
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    item: ItemHit
    incident: IncidentHit
    critic: CriticVerdict


class SearchResponse(BaseModel):
    """Response body for POST /api/v1/incidents/search matching search-contract-v1."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    query: str
    total_hits: int = Field(..., ge=0)
    execution_time_ms: float = Field(..., ge=0.0)
    hits: list[SearchHit]


# =============================================================================
# Candidate Model (Internal Representation from RPC / DB)
# =============================================================================


class EvidenceCandidate(BaseModel):
    """Evidence candidate row returned from search_evidence_items RPC or candidate store."""

    model_config = ConfigDict(extra="ignore")

    incident_id: str
    model_run_id: str
    playback_url: str
    incident_type: str
    severity_level: int
    incident_title: str | None = None
    incident_description: str
    incident_window: list[float]
    item_type: Literal["entity", "instrument", "asset"]
    item_id: str
    item_name: str
    item_label: str
    item_description: str
    threat_level: int | None = None
    holder_entity_id: str | None = None
    crop_image_url: str
    timestamp_seconds: int
    bounding_box: list[int] | None = None
    similarity_score: float


# Canned candidate data matching mock-backend/base_profile_mock for local / fallback execution
_DEFAULT_CANDIDATES: list[dict[str, Any]] = [
    {
        "incident_id": "Assault007_x264",
        "model_run_id": "m86a5c319e26659804b0",
        "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007_x264.mp4",
        "incident_type": "assault",
        "severity_level": 4,
        "incident_title": "Physical altercation with edged weapon in ATM lobby",
        "incident_description": (
            "An altercation ensues where a perpetrator brandishes a large blade against a victim."
        ),
        "incident_window": [10.0, 28.0],
        "item_type": "instrument",
        "item_id": "I1",
        "item_name": "machete",
        "item_label": "machete",
        "item_description": "Long curved blade held by assailant during storefront altercation.",
        "threat_level": 4,
        "holder_entity_id": "E1",
        "crop_image_url": (
            "https://pub-r2.example.com/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg"
        ),
        "timestamp_seconds": 14,
        "bounding_box": [320, 450, 510, 600],
        "similarity_score": 0.89,
    },
    {
        "incident_id": "Assault007_x264",
        "model_run_id": "m86a5c319e26659804b0",
        "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007_x264.mp4",
        "incident_type": "assault",
        "severity_level": 4,
        "incident_title": "Physical altercation with edged weapon in ATM lobby",
        "incident_description": (
            "An altercation ensues where a perpetrator brandishes a large blade against a victim."
        ),
        "incident_window": [10.0, 28.0],
        "item_type": "entity",
        "item_id": "E1",
        "item_name": "perpetrator",
        "item_label": "person",
        "item_description": "Adult wearing dark hooded jacket lunging toward victim.",
        "threat_level": 5,
        "holder_entity_id": None,
        "crop_image_url": "https://pub-r2.example.com/evidence/Assault007_x264/m86a5c319e26659804b0/entities/E1.jpg",
        "timestamp_seconds": 12,
        "bounding_box": [210, 390, 820, 640],
        "similarity_score": 0.81,
    },
    {
        "incident_id": "Burglary004_x264",
        "model_run_id": "m71b9c240a15549703f1",
        "playback_url": "https://pub-r2.example.com/videos/anomaly/burglary/Burglary004_x264.mp4",
        "incident_type": "burglary",
        "severity_level": 3,
        "incident_title": "Storefront forced entry with pry bar",
        "incident_description": "Perpetrator uses a metal pry bar to breach commercial storefront doors.",
        "incident_window": [15.0, 45.0],
        "item_type": "instrument",
        "item_id": "I1",
        "item_name": "crowbar",
        "item_label": "crowbar",
        "item_description": "Heavy metal pry bar used to force open the storefront entrance door.",
        "threat_level": 3,
        "holder_entity_id": "E1",
        "crop_image_url": (
            "https://pub-r2.example.com/evidence/Burglary004_x264/m71b9c240a15549703f1/instruments/I1.jpg"
        ),
        "timestamp_seconds": 22,
        "bounding_box": [410, 520, 580, 690],
        "similarity_score": 0.78,
    },
    {
        "incident_id": "RoadAccidents010_x264",
        "model_run_id": "m42c8d119e34418602a8",
        "playback_url": "https://pub-r2.example.com/videos/anomaly/road_accidents/RoadAccidents010_x264.mp4",
        "incident_type": "road accident",
        "severity_level": 2,
        "incident_title": "Vehicle collision at suburban intersection",
        "incident_description": "A silver vehicle fails to yield and collides with another car.",
        "incident_window": [4.0, 14.0],
        "item_type": "asset",
        "item_id": "A1",
        "item_name": "silver hatchback",
        "item_label": "car",
        "item_description": "Silver compact sedan involved in front-quarter collision at street intersection.",
        "threat_level": 2,
        "holder_entity_id": None,
        "crop_image_url": "https://pub-r2.example.com/evidence/RoadAccidents010_x264/m42c8d119e34418602a8/assets/A1.jpg",
        "timestamp_seconds": 6,
        "bounding_box": None,
        "similarity_score": 0.74,
    },
    {
        "incident_id": "Assault007_x264",
        "model_run_id": "m86a5c319e26659804b0",
        "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007_x264.mp4",
        "incident_type": "assault",
        "severity_level": 4,
        "incident_title": "Physical altercation with edged weapon in ATM lobby",
        "incident_description": (
            "An altercation ensues where a perpetrator brandishes a large blade against a victim."
        ),
        "incident_window": [10.0, 28.0],
        "item_type": "instrument",
        "item_id": "I2",
        "item_name": "cell phone",
        "item_label": "cell phone",
        "item_description": "Black handheld mobile smartphone held by bystander.",
        "threat_level": 1,
        "holder_entity_id": "E2",
        "crop_image_url": (
            "https://pub-r2.example.com/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I2.jpg"
        ),
        "timestamp_seconds": 18,
        "bounding_box": [500, 310, 560, 370],
        "similarity_score": 0.42,
    },
]


# =============================================================================
# Hexagonal Ports & Adapters
# =============================================================================


class SearchStore(ABC):
    """Port for candidate retrieval via search_evidence_items RPC and query auditing."""

    @abstractmethod
    async def search_evidence_items(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        min_similarity: float = 0.2,
        item_types: list[str] | None = None,
        incident_types: list[str] | None = None,
        min_severity: int | None = None,
        max_severity: int | None = None,
    ) -> list[EvidenceCandidate]:
        """Execute pgvector search over official evidence crops with metadata filters."""
        pass

    @abstractmethod
    async def persist_query(self, query_id: str, query: str) -> None:
        """Persist natural language search query record into the data layer."""
        pass

    @abstractmethod
    async def persist_query_results(self, query_id: str, results: list[dict[str, Any]]) -> None:
        """Persist ranked result rows (rank, similarity, critic verdict) into the data layer."""
        pass


class InMemorySearchStore(SearchStore):
    """In-memory candidate store and query audit log for testing and zero-VM environments."""

    def __init__(self, candidates: list[EvidenceCandidate] | None = None) -> None:
        if candidates is not None:
            self.candidates = candidates
        else:
            self.candidates = [EvidenceCandidate.model_validate(c) for c in _DEFAULT_CANDIDATES]
        self.queries: dict[str, dict[str, Any]] = {}
        self.query_results: list[dict[str, Any]] = []

    async def search_evidence_items(
        self,
        query_embedding: list[float],  # noqa: ARG002
        top_k: int = 10,
        min_similarity: float = 0.2,
        item_types: list[str] | None = None,
        incident_types: list[str] | None = None,
        min_severity: int | None = None,
        max_severity: int | None = None,
    ) -> list[EvidenceCandidate]:
        matched: list[EvidenceCandidate] = []
        item_types_set = set(item_types) if item_types else None
        incident_types_set = set(incident_types) if incident_types else None

        for cand in self.candidates:
            if cand.similarity_score < min_similarity:
                continue
            if item_types_set and cand.item_type not in item_types_set:
                continue
            if incident_types_set and cand.incident_type not in incident_types_set:
                continue
            if min_severity is not None and cand.severity_level < min_severity:
                continue
            if max_severity is not None and cand.severity_level > max_severity:
                continue
            matched.append(cand)

        matched.sort(key=lambda c: c.similarity_score, reverse=True)
        return matched[:top_k]

    async def persist_query(self, query_id: str, query: str) -> None:
        self.queries[query_id] = {
            "id": query_id,
            "query_text": query,
            "submitted_datetime": _dt.datetime.now(_dt.UTC).isoformat(),
        }

    async def persist_query_results(self, query_id: str, results: list[dict[str, Any]]) -> None:
        for row in results:
            self.query_results.append({"query_id": query_id, **row})


def _parse_timestamp_seconds(ts: Any) -> float:
    """Parse a timestamp into seconds offset as float."""
    if ts is None:
        return 0.0
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip()
    if not s:
        return 0.0
    if ":" in s:
        parts = s.split(":")
        try:
            return float(sum(float(p) * (60**i) for i, p in enumerate(reversed(parts))))
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


class SupabaseSearchStore(SearchStore):
    """Supabase PostgREST candidate store and query audit log querying search_evidence_items RPC."""

    def __init__(
        self,
        client: Any = None,
        r2_resolver: Any = None,
    ) -> None:
        self._client = client
        self._r2_resolver = r2_resolver or resolve_r2_url

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        db = await incident_db.get_db()
        if db is None:
            raise RuntimeError(
                "Incident Supabase DB is not configured (INCIDENT_SUPABASE_URL and "
                "INCIDENT_SUPABASE_SERVICE_ROLE_KEY required)"
            )
        return db.client

    async def search_evidence_items(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        min_similarity: float = 0.2,
        item_types: list[str] | None = None,
        incident_types: list[str] | None = None,
        min_severity: int | None = None,
        max_severity: int | None = None,
    ) -> list[EvidenceCandidate]:
        if not query_embedding:
            return []

        client = await self._get_client()

        params: dict[str, Any] = {
            "p_query_embedding": query_embedding,
            "p_top_k": top_k,
            "p_min_similarity": min_similarity,
            "p_item_types": item_types if item_types else ["entity", "instrument", "asset"],
            "p_incident_types": incident_types,
            "p_min_severity": min_severity,
            "p_max_severity": max_severity,
        }

        resp = await client.rpc("search_evidence_items", params).execute()
        rows = resp.data or []

        candidates: list[EvidenceCandidate] = []
        for row in rows:
            image_ref = row.get("image") or row.get("crop_image_url") or ""
            crop_image_url = self._r2_resolver(image_ref)

            video_ref = row.get("video_filepath") or row.get("playback_url") or ""
            playback_url = self._r2_resolver(video_ref)

            if "incident_window" in row and isinstance(row["incident_window"], list):
                incident_window = [float(x) for x in row["incident_window"][:2]]
            else:
                start_sec = _parse_timestamp_seconds(row.get("incident_start_timestamp"))
                end_sec = _parse_timestamp_seconds(row.get("incident_end_timestamp"))
                incident_window = [start_sec, max(start_sec, end_sec)]

            raw_item_type = str(row.get("item_type", "entity")).lower()
            item_type: Literal["entity", "instrument", "asset"]
            if raw_item_type in ("entity", "instrument", "asset"):
                item_type = raw_item_type  # type: ignore[assignment]
            else:
                item_type = "entity"

            cand = EvidenceCandidate(
                incident_id=str(row.get("incident_id", "")),
                model_run_id=str(row.get("model_run_id", "")),
                playback_url=playback_url,
                incident_type=str(row.get("incident_type", "unknown")),
                severity_level=int(row.get("severity_level", 1)),
                incident_title=row.get("incident_title") or row.get("title"),
                incident_description=str(row.get("incident_description") or ""),
                incident_window=incident_window,
                item_type=item_type,
                item_id=str(row.get("item_id", "")),
                item_name=str(row.get("item_name") or ""),
                item_label=str(row.get("item_label") or row.get("item_name") or ""),
                item_description=str(row.get("item_description") or row.get("description") or ""),
                threat_level=int(row["threat_level"]) if row.get("threat_level") is not None else None,
                holder_entity_id=row.get("holder_entity_id"),
                crop_image_url=crop_image_url,
                timestamp_seconds=int(row.get("timestamp_seconds", 0)),
                bounding_box=row.get("bounding_box"),
                similarity_score=float(row.get("similarity_score", 0.0)),
            )
            candidates.append(cand)

        return candidates

    async def persist_query(self, query_id: str, query: str) -> None:
        try:
            client = await self._get_client()
            data = {
                "id": query_id,
                "query_text": query,
                "submitted_datetime": _dt.datetime.now(_dt.UTC).replace(tzinfo=None).isoformat(),
            }
            await client.table("queries").upsert(data, on_conflict="id").execute()
        except Exception as exc:
            logger.warning("Failed to persist query '%s' to Supabase queries table: %s", query_id, exc)

    async def persist_query_results(self, query_id: str, results: list[dict[str, Any]]) -> None:
        if not results:
            return
        try:
            client = await self._get_client()
            rows = [
                {
                    "id": r["id"],
                    "query_id": query_id,
                    "incident_id": r["incident_id"],
                    "model_run_id": r["model_run_id"],
                    "item_type": r["item_type"],
                    "item_id": r["item_id"],
                    "rank": r["rank"],
                    "similarity_score": r["similarity_score"],
                    "critic_verdict": r["critic_verdict"],
                    "critic_rationale": r.get("critic_rationale"),
                    "retrieved_at": r.get(
                        "retrieved_at",
                        _dt.datetime.now(_dt.UTC).replace(tzinfo=None).isoformat(),
                    ),
                }
                for r in results
            ]
            await client.table("query_results").upsert(rows, on_conflict="id").execute()
        except Exception as exc:
            logger.warning("Failed to persist query_results for '%s' to Supabase: %s", query_id, exc)


def get_default_search_store() -> SearchStore:
    """Resolve the default SearchStore based on environment and configuration.

    Selection policy:
    1. Check INCIDENT_SEARCH_STORE environment variable:
       - 'memory' -> InMemorySearchStore()
       - 'supabase' -> SupabaseSearchStore()
    2. Fallback based on database configuration:
       - If incident_db.is_configured() -> SupabaseSearchStore()
       - Otherwise -> InMemorySearchStore() (for local zero-VM/mock use)
    """
    mode = (os.getenv("INCIDENT_SEARCH_STORE") or "").strip().lower()
    if mode == "memory":
        return InMemorySearchStore()
    if mode == "supabase":
        return SupabaseSearchStore()

    if incident_db.is_configured():
        return SupabaseSearchStore()
    return InMemorySearchStore()


# =============================================================================
# Query Text Embedder Port & Default Adapter
# =============================================================================


class QueryEmbedder(ABC):
    """Port for generating query text embeddings for pgvector search."""

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Produce a normalized 1024-dimensional embedding vector for query text."""
        pass


class DefaultQueryEmbedder(QueryEmbedder):
    """Default query text embedder adapter.

    TODO(PR-120): Owned by PR #120 / PR #119 (embedding benchmark and selection).
    Wire this adapter to the chosen embedding model (NeMo / text-embedding-3 / MiniLM)
    once finalized.
    """

    def __init__(self, vector_dim: int = 1024) -> None:
        self.vector_dim = vector_dim

    async def embed_query(self, query: str) -> list[float]:
        # Deterministic normalized unit vector placeholder for query text
        val = sum(ord(c) for c in query) % 100 / 100.0
        vec = [val] * self.vector_dim
        norm = (sum(x * x for x in vec)) ** 0.5 or 1.0
        return [round(x / norm, 6) for x in vec]


# =============================================================================
# Always-On Critic Port & VLM Adapter
# =============================================================================


class CriticEvaluator(ABC):
    """Port for the always-on vision-language critic."""

    @abstractmethod
    async def evaluate_candidate(
        self,
        query: str,
        item: ItemHit,
        incident: IncidentHit,
    ) -> CriticVerdict:
        """Evaluate a candidate crop image and metadata against the search query."""
        pass


class VlmCriticEvaluator(CriticEvaluator):
    """VLM Critic evaluator using OpenAI-compatible chat completions endpoint (Brev Switchyard)."""

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = DEFAULT_CRITIC_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("VLM_BASE_URL") or DEFAULT_VLM_BASE_URL).rstrip("/")
        self.model_name = model_name or os.getenv("VLM_NAME") or DEFAULT_VLM_MODEL
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def _chat_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _build_critic_prompt(self, query: str, item: ItemHit, incident: IncidentHit) -> str:
        return (
            "You are an always-on incident evidence verification critic.\n"
            "Evaluate whether the retrieved evidence crop image and item metadata match the search query.\n\n"
            f'Search query: "{query}"\n\n'
            f"Candidate Evidence Item:\n"
            f"- Category: {item.item_type}\n"
            f"- ID: {item.item_id}\n"
            f"- Name: {item.name}\n"
            f"- Short label: {item.label}\n"
            f"- Description: {item.description}\n"
            f"- Threat level: {item.threat_level}\n\n"
            f"Parent Incident:\n"
            f"- Type: {incident.incident_type}\n"
            f"- Severity: {incident.severity_level}\n"
            f"- Description: {incident.description}\n\n"
            "Rubric:\n"
            "1. Does the object in the crop image match the user's semantic query?\n"
            "2. Is the candidate an adversarial distractor (e.g. user asked for 'firearm', candidate is a phone)?\n"
            "Return JSON in the exact format:\n"
            "{\n"
            '  "verdict": "confirmed" | "rejected" | "unverified",\n'
            '  "confidence": <float between 0.0 and 1.0 or null>,\n'
            '  "rationale": "<brief, objective explanation justifying the verdict>"\n'
            "}"
        )

    async def evaluate_candidate(
        self,
        query: str,
        item: ItemHit,
        incident: IncidentHit,
    ) -> CriticVerdict:
        """Call VLM critic to evaluate candidate against query.

        Failure rule: on any exception, network failure, or timeout, NEVER drop the hit silently.
        Degrade gracefully to verdict='unverified' with an informative rationale.
        """
        try:
            prompt = self._build_critic_prompt(query, item, incident)
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            content_payload: list[dict[str, Any]] = []
            if item.crop_image_url and (
                item.crop_image_url.startswith("http://") or item.crop_image_url.startswith("https://")
            ):
                content_payload.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": item.crop_image_url},
                    }
                )
            content_payload.append({"type": "text", "text": prompt})

            request_body = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": content_payload}],
                "stream": False,
                "temperature": 0.0,
                "max_tokens": 512,
                "response_format": {"type": "json_object"},
            }

            if self._http_client is not None:
                resp = await self._http_client.post(
                    self._chat_url(), json=request_body, headers=headers, timeout=self.timeout_seconds
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.post(self._chat_url(), json=request_body, headers=headers)

            if resp.status_code >= 400:
                logger.warning(
                    "Critic call returned HTTP %d for item %s: %s", resp.status_code, item.item_id, resp.text[:200]
                )
                return CriticVerdict(
                    verdict="unverified",
                    confidence=None,
                    rationale=f"Critic endpoint returned HTTP {resp.status_code}",
                )

            body = resp.json()
            raw_text = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            data = json.loads(raw_text)

            raw_verdict = str(data.get("verdict", "")).strip().lower()
            verdict: Literal["confirmed", "rejected", "unverified"]
            if raw_verdict == "confirmed":
                verdict = "confirmed"
            elif raw_verdict == "rejected":
                verdict = "rejected"
            else:
                verdict = "unverified"
            raw_conf = data.get("confidence")
            confidence = (
                float(raw_conf)
                if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool) and 0.0 <= raw_conf <= 1.0
                else None
            )
            rationale = str(data.get("rationale") or f"Model returned verdict {verdict}").strip()

            return CriticVerdict(verdict=verdict, confidence=confidence, rationale=rationale)

        except Exception as exc:
            logger.warning(
                "Critic evaluation failed for item %s: %s; degrading to unverified", item.item_id, exc, exc_info=False
            )
            return CriticVerdict(
                verdict="unverified",
                confidence=None,
                rationale=f"Critic verification failed: {exc}",
            )


# =============================================================================
# Router & Registration
# =============================================================================


def create_incident_search_router(
    config: Any = None,  # noqa: ARG001
    store: SearchStore | None = None,
    critic: CriticEvaluator | None = None,
    embedder: QueryEmbedder | None = None,
    critic_delay_seconds: float | None = None,
) -> APIRouter:
    """Build the POST /api/v1/incidents/search router implementing search-contract-v1."""
    router = APIRouter()
    search_store = store if store is not None else get_default_search_store()
    critic_evaluator = critic or VlmCriticEvaluator()
    query_embedder = embedder or DefaultQueryEmbedder()

    @router.post(
        "/api/v1/incidents/search",
        summary="Search incident evidence items using natural language with always-on critic",
        tags=["Incident Search"],
        response_model=SearchResponse,
    )
    async def search_incidents(req: SearchRequest) -> dict[str, Any]:
        t0 = time.perf_counter()
        query_id = f"q-{uuid.uuid4().hex[:12]}"

        # 1. Embed query text
        query_embedding = await query_embedder.embed_query(req.query)

        # 2. Retrieve candidate items through SearchStore port
        item_types: list[str] | None = (
            [str(t) for t in req.filters.item_types] if req.filters and req.filters.item_types else None
        )
        incident_types = req.filters.incident_types if req.filters and req.filters.incident_types else None
        min_sev = req.filters.min_severity if req.filters else None
        max_sev = req.filters.max_severity if req.filters else None

        candidates = await search_store.search_evidence_items(
            query_embedding=query_embedding,
            top_k=req.top_k,
            min_similarity=req.min_similarity,
            item_types=item_types,
            incident_types=incident_types,
            min_severity=min_sev,
            max_severity=max_sev,
        )

        # 3. Always-on critic evaluation per candidate hit with configurable delay spacing
        delay = _get_critic_delay_seconds(critic_delay_seconds)

        async def _evaluate_hit(rank: int, cand: EvidenceCandidate) -> SearchHit:
            item = ItemHit(
                item_type=cand.item_type,
                item_id=cand.item_id,
                name=cand.item_name,
                label=cand.item_label,
                description=cand.item_description,
                threat_level=cand.threat_level,
                holder_entity_id=cand.holder_entity_id,
                crop_image_url=cand.crop_image_url,
                timestamp_seconds=cand.timestamp_seconds,
                bounding_box=cand.bounding_box,
            )
            incident = IncidentHit(
                incident_id=cand.incident_id,
                model_run_id=cand.model_run_id,
                incident_type=cand.incident_type,
                severity_level=cand.severity_level,
                title=cand.incident_title,
                description=cand.incident_description,
                playback_url=cand.playback_url,
                incident_window=cand.incident_window,
            )
            try:
                verdict = await critic_evaluator.evaluate_candidate(req.query, item, incident)
            except Exception as exc:
                logger.warning(
                    "Critic evaluation failed in route for item %s: %s; degrading to unverified",
                    cand.item_id,
                    exc,
                )
                verdict = CriticVerdict(
                    verdict="unverified",
                    confidence=None,
                    rationale=f"Critic verification failed: {exc}",
                )
            return SearchHit(
                result_id=f"res-{uuid.uuid4().hex[:8]}",
                rank=rank,
                similarity_score=cand.similarity_score,
                item=item,
                incident=incident,
                critic=verdict,
            )

        eval_tasks: list[asyncio.Task[SearchHit]] = []
        for idx, cand in enumerate(candidates):
            rank = idx + 1
            if idx > 0 and delay > 0:
                await asyncio.sleep(delay)
            eval_tasks.append(asyncio.create_task(_evaluate_hit(rank, cand)))

        hits: list[SearchHit] = await asyncio.gather(*eval_tasks) if eval_tasks else []

        # 4. Persist query and query_results audit trail through SearchStore port
        try:
            await search_store.persist_query(query_id, req.query)
            if hits:
                results_to_persist = [
                    {
                        "id": hit.result_id,
                        "incident_id": hit.incident.incident_id,
                        "model_run_id": hit.incident.model_run_id,
                        "item_type": hit.item.item_type,
                        "item_id": hit.item.item_id,
                        "rank": hit.rank,
                        "similarity_score": hit.similarity_score,
                        "critic_verdict": hit.critic.verdict,
                        "critic_rationale": hit.critic.rationale,
                        "retrieved_at": _dt.datetime.now(_dt.UTC).isoformat(),
                    }
                    for hit in hits
                ]
                await search_store.persist_query_results(query_id, results_to_persist)
        except Exception as exc:
            logger.error("Failed to persist search query/results audit for query_id=%s: %s", query_id, exc)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        response = SearchResponse(
            query_id=query_id,
            query=req.query,
            total_hits=len(hits),
            execution_time_ms=elapsed_ms,
            hits=hits,
        )
        return response.model_dump()

    return router


def register_incident_search_routes(
    app: FastAPI,
    config: Any = None,
    store: SearchStore | None = None,
    critic: CriticEvaluator | None = None,
    embedder: QueryEmbedder | None = None,
    critic_delay_seconds: float | None = None,
) -> None:
    """Register POST /api/v1/incidents/search on the FastAPI application.

    The search route is always-on with no feature flag, matching the MVP2 architecture specification.
    """
    try:
        app.include_router(
            create_incident_search_router(
                config=config,
                store=store,
                critic=critic,
                embedder=embedder,
                critic_delay_seconds=critic_delay_seconds,
            )
        )
        logger.info("Registered POST /api/v1/incidents/search (Always-On Critic)")
    except Exception as exc:
        logger.error("Failed to register incident search route: %s", exc, exc_info=True)
        raise
