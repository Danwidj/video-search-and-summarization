# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident search endpoint implementing search-contract-v1."""

from __future__ import annotations

import time
from typing import Any
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic import Field

router = APIRouter(prefix="/api/v1")


class SearchFilters(BaseModel):
    incident_types: list[str] | None = None
    min_severity: int | None = Field(default=None, ge=1, le=5)
    max_severity: int | None = Field(default=None, ge=1, le=5)
    item_types: list[str] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.2, ge=0.0, le=1.0)
    item_types: list[str] = Field(default=["entity", "instrument", "asset"])
    filters: SearchFilters | None = None


_CANNED_HITS: list[dict[str, Any]] = [
    {
        "item": {
            "item_type": "instrument",
            "item_id": "I1",
            "name": "machete",
            "label": "machete",
            "description": "Long curved blade held by assailant during storefront altercation.",
            "threat_level": 4,
            "holder_entity_id": "E1",
            "crop_image_url": "https://pub-r2.example.com/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg",
            "timestamp_seconds": 14,
            "bounding_box": [320, 450, 510, 600],
        },
        "incident": {
            "incident_id": "Assault007_x264",
            "model_run_id": "m86a5c319e26659804b0",
            "incident_type": "assault",
            "severity_level": 4,
            "title": "Physical altercation with edged weapon in ATM lobby",
            "description": "An altercation ensues where a perpetrator brandishes a large blade against a victim.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007_x264.mp4",
            "incident_window": [10.0, 28.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.96,
            "rationale": "The cropped screenshot clearly shows a machete with a curved metal blade held in the subject's right hand.",
        },
        "similarity_score": 0.89,
    },
    {
        "item": {
            "item_type": "entity",
            "item_id": "E1",
            "name": "perpetrator",
            "label": "person",
            "description": "Adult wearing dark hooded jacket lunging toward victim.",
            "threat_level": 5,
            "holder_entity_id": None,
            "crop_image_url": "https://pub-r2.example.com/evidence/Assault007_x264/m86a5c319e26659804b0/entities/E1.jpg",
            "timestamp_seconds": 12,
            "bounding_box": [210, 390, 820, 640],
        },
        "incident": {
            "incident_id": "Assault007_x264",
            "model_run_id": "m86a5c319e26659804b0",
            "incident_type": "assault",
            "severity_level": 4,
            "title": "Physical altercation with edged weapon in ATM lobby",
            "description": "An altercation ensues where a perpetrator brandishes a large blade against a victim.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007_x264.mp4",
            "incident_window": [10.0, 28.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.94,
            "rationale": "The crop clearly depicts the primary aggressor in active motion.",
        },
        "similarity_score": 0.81,
    },
    {
        "item": {
            "item_type": "instrument",
            "item_id": "I1",
            "name": "crowbar",
            "label": "crowbar",
            "description": "Heavy metal pry bar used to force open the storefront entrance door.",
            "threat_level": 3,
            "holder_entity_id": "E1",
            "crop_image_url": "https://pub-r2.example.com/evidence/Burglary004_x264/m71b9c240a15549703f1/instruments/I1.jpg",
            "timestamp_seconds": 22,
            "bounding_box": [410, 520, 580, 690],
        },
        "incident": {
            "incident_id": "Burglary004_x264",
            "model_run_id": "m71b9c240a15549703f1",
            "incident_type": "burglary",
            "severity_level": 3,
            "title": "Storefront forced entry with pry bar",
            "description": "Perpetrator uses a metal pry bar to breach commercial storefront doors.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/burglary/Burglary004_x264.mp4",
            "incident_window": [15.0, 45.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.92,
            "rationale": "The crop shows an angled pry bar applied against the glass door frame.",
        },
        "similarity_score": 0.78,
    },
    {
        "item": {
            "item_type": "asset",
            "item_id": "A1",
            "name": "silver hatchback",
            "label": "car",
            "description": "Silver compact sedan involved in front-quarter collision at street intersection.",
            "threat_level": 2,
            "holder_entity_id": None,
            "crop_image_url": "https://pub-r2.example.com/evidence/RoadAccidents010_x264/m42c8d119e34418602a8/assets/A1.jpg",
            "timestamp_seconds": 6,
            "bounding_box": None,
        },
        "incident": {
            "incident_id": "RoadAccidents010_x264",
            "model_run_id": "m42c8d119e34418602a8",
            "incident_type": "road_accident",
            "severity_level": 2,
            "title": "Vehicle collision at suburban intersection",
            "description": "A silver vehicle fails to yield and collides with another car.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/road_accidents/RoadAccidents010_x264.mp4",
            "incident_window": [4.0, 14.0],
        },
        "critic": {
            "verdict": "confirmed",
            "confidence": 0.95,
            "rationale": "The crop shows the damaged front bumper and side panel of the silver hatchback.",
        },
        "similarity_score": 0.74,
    },
    {
        "item": {
            "item_type": "instrument",
            "item_id": "I2",
            "name": "cell phone",
            "label": "cell phone",
            "description": "Black handheld mobile smartphone held by bystander.",
            "threat_level": 1,
            "holder_entity_id": "E2",
            "crop_image_url": "https://pub-r2.example.com/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I2.jpg",
            "timestamp_seconds": 18,
            "bounding_box": [500, 310, 560, 370],
        },
        "incident": {
            "incident_id": "Assault007_x264",
            "model_run_id": "m86a5c319e26659804b0",
            "incident_type": "assault",
            "severity_level": 4,
            "title": "Physical altercation with edged weapon in ATM lobby",
            "description": "An altercation ensues where a perpetrator brandishes a large blade against a victim.",
            "playback_url": "https://pub-r2.example.com/videos/anomaly/assault/Assault007_x264.mp4",
            "incident_window": [10.0, 28.0],
        },
        "critic": {
            "verdict": "rejected",
            "confidence": 0.88,
            "rationale": "Candidate is a handheld electronic device, not a weapon or threat.",
        },
        "similarity_score": 0.42,
    },
]


@router.post("/incidents/search")
async def search_incidents(req: SearchRequest) -> dict[str, Any]:
    t0 = time.perf_counter()

    allowed_item_types = set(req.item_types)
    if req.filters and req.filters.item_types:
        allowed_item_types &= set(req.filters.item_types)

    incident_types = set(req.filters.incident_types) if req.filters and req.filters.incident_types else None
    min_sev = req.filters.min_severity if req.filters else None
    max_sev = req.filters.max_severity if req.filters else None

    matched = []
    for candidate in _CANNED_HITS:
        item = candidate["item"]
        incident = candidate["incident"]
        sim = candidate["similarity_score"]

        if sim < req.min_similarity:
            continue
        if item["item_type"] not in allowed_item_types:
            continue
        if incident_types and incident["incident_type"] not in incident_types:
            continue
        if min_sev is not None and incident["severity_level"] < min_sev:
            continue
        if max_sev is not None and incident["severity_level"] > max_sev:
            continue

        matched.append(candidate)

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
