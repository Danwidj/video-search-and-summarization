# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident analysis endpoint backed by the shared async incident writer.

Like the real agent it inserts one ``model_runs`` row and one AI ``report_revisions`` row per call
(a new branch each time, copying nothing from earlier revisions) and returns the ``revision_id``.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

from base_profile_mock.routers.vst_storage import _upload_key
from base_profile_mock.state import AppState
from base_profile_mock.state import Stream
from base_profile_mock.state import get_state

router = APIRouter(prefix="/api/v1")
_locks: dict[str, asyncio.Lock] = {}

_MOCK_CATEGORIES = (
    {
        "type": "road accident",
        "folder": "road_accidents",
        "description": "MOCK incident report: vehicles are involved in a road accident.",
        "severity": 4,
        "confidence": 0.88,
    },
    {
        "type": "assault",
        "folder": "fighting",
        "description": "MOCK incident report: two people are involved in a physical altercation.",
        "severity": 3,
        "confidence": 0.91,
    },
    {
        "type": "animal attack",
        "folder": "animal_attacks",
        "description": "MOCK incident report: an animal-related safety incident is visible.",
        "severity": 2,
        "confidence": 0.84,
    },
    {
        "type": "burglary",
        "folder": "burglary",
        "description": "MOCK incident report: a suspicious entry or burglary-like event is visible.",
        "severity": 4,
        "confidence": 0.86,
    },
    {
        "type": "explosion",
        "folder": "explosion",
        "description": "MOCK incident report: an explosion-like event is visible.",
        "severity": 5,
        "confidence": 0.83,
    },
)


_EMBEDDING_DIMENSIONS = 1024


class EvidenceEmbeddingsRequest(BaseModel):
    revision_id: int = Field(..., ge=1)


class AnalyzeRequest(BaseModel):
    reasoning: bool = False
    model_run_id: str | None = Field(default=None, min_length=1, max_length=20)
    model: str | None = Field(default=None, min_length=1, description="Model id from the shared allowlist.")
    reviewer_prompt: str | None = Field(default=None, max_length=1000)


@lru_cache(maxsize=1)
def _allowed_models() -> tuple[str, ...]:
    """The VLM allowlist shared with the agent and console (``contracts/inference.json``)."""
    path = Path(__file__).resolve().parents[5] / "contracts" / "inference.json"
    return tuple(str(model["id"]) for model in json.loads(path.read_text(encoding="utf-8"))["models"])


def _writer_module():
    root = Path(__file__).resolve().parents[9] / "services" / "agent" / "src"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from vss_agents.utils import incident_db

    return incident_db


def _mock_category(incident_id: str) -> dict[str, object]:
    digest = hashlib.sha256(incident_id.encode("utf-8")).digest()
    return _MOCK_CATEGORIES[digest[0] % len(_MOCK_CATEGORIES)]


def _mock_report(category: dict[str, object]) -> dict[str, object]:
    """A small incident-contract-v4 report: one incident and one human entity."""
    return {
        "incident": {
            "type": category["type"],
            "title": f"MOCK {category['type']}",
            "start_timestamp": 0,
            "end_timestamp": 10,
            "description": category["description"],
            "severity_level": category["severity"],
            "severity_reason": "MOCK severity; no VSS inference was run.",
            "confidence_score": category["confidence"],
            "location": "unknown",
        },
        "entities": [
            {
                "entity_id": "E1",
                "type": "human",
                "description": "MOCK detected person involved in the incident.",
                "timestamp_seconds": 2,
                "first_seen_seconds": 1,
                "last_seen_seconds": 6,
                "label": "person",
            }
        ],
        "instruments": [],
        "assets": [],
        "timeline": [],
        "uncertainties": [],
    }


def _mock_evidence(report: dict[str, object]) -> list[dict[str, object]]:
    """Evidence entries for a mock report; the mock produces no crops, so every image is a recorded gap."""
    entities = report["entities"]
    assert isinstance(entities, list)
    return [
        {
            "item_type": "entity",
            "item_id": entity["entity_id"],
            "item_name": entity["type"],
            "description": entity["description"],
            "threat_level": None,
            "holder_entity_id": None,
            "timestamp_seconds": entity["timestamp_seconds"],
            "first_seen_seconds": entity["first_seen_seconds"],
            "last_seen_seconds": entity["last_seen_seconds"],
            "label": entity["label"],
            "bounding_box": None,
            "image": None,
            "image_gap": "mock backend: no frames were analysed, so no evidence image exists",
        }
        for entity in entities
    ]


def _r2_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise HTTPException(503, "R2 upload support is not installed for the mock backend") from exc

    required = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise HTTPException(503, f"R2 storage is not configured; missing {', '.join(missing)}")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}),
    )


def _upload_video_to_r2(*, stream: Stream, incident_id: str, category: dict[str, object]) -> str:
    del incident_id, category
    key = _upload_key(stream, stream.stream_id)
    _r2_client().put_object(
        Bucket=os.environ["R2_BUCKET"],
        Key=key,
        Body=stream.content,
        ContentType="video/mp4",
    )
    return key


def _is_r2_object_key(filepath: object) -> bool:
    return isinstance(filepath, str) and bool(filepath) and not filepath.startswith(("/", "http://", "https://"))


@router.post("/incidents/{incident_id}/analyze")
async def analyze_incident(
    incident_id: str, body: AnalyzeRequest, state: AppState = Depends(get_state)
) -> dict[str, object]:
    """Persist one explicitly mock report for an uploaded video.

    The normalized schema stores only an R2 object key in ``videos.filepath``.
    A frontend upload is categorized here, then the uploaded bytes are copied to
    R2 before the revision rows are written.
    """
    if not incident_id or len(incident_id) > 20:
        raise HTTPException(400, "invalid video id")
    if body.model is not None and body.model not in _allowed_models():
        raise HTTPException(400, f"Model {body.model!r} is not in the incident contract allowlist")
    writer = _writer_module()
    db = await writer.get_db()
    if db is None:
        raise HTTPException(503, "incident database is not configured or unavailable")
    lock = _locks.setdefault(incident_id, asyncio.Lock())
    async with lock:
        video = await db.get_video(incident_id)
        if video is None:
            raise HTTPException(404, "video not found")
        category = _mock_category(incident_id)
        source = video.get("source")
        object_key = video.get("filepath") if _is_r2_object_key(video.get("filepath")) else None
        if object_key is None:
            if not source:
                raise HTTPException(409, "video has no upload source and no R2 object key")
            async with state.lock:
                stream = state.streams.get(source)
            if stream is None or not stream.content:
                raise HTTPException(409, "uploaded video bytes are not available in the mock backend")
            object_key = _upload_video_to_r2(stream=stream, incident_id=incident_id, category=category)
        caller_owns_run = body.model_run_id is not None
        model_run_id = body.model_run_id or "mock-run-" + uuid.uuid4().hex[:11]
        model_name = body.model or "base-profile-mock"
        report = _mock_report(category)
        evidence = _mock_evidence(report)
        await db.update_video(incident_id, filepath=object_key)
        if caller_owns_run:
            await db.insert_model_run_if_absent(model_run_id, model_name=model_name)
        else:
            await db.insert_model_run(
                model_run_id,
                model_name=model_name,
                model_version="mock-v1",
                prompt_version="mock-incident-v1",
                notes="MOCK output generated by base_profile_mock; no VSS inference was run.",
            )
        revision = await db.insert_ai_revision(
            incident_id,
            model_run_id=model_run_id,
            payload=report,
            evidence=evidence,
            note=f"Reviewer prompt: {body.reviewer_prompt}" if body.reviewer_prompt else None,
        )
    return {
        "status": "completed",
        "video_id": incident_id,
        "model_run_id": model_run_id,
        "revision_id": revision["id"],
        "incident_type": category["type"],
        "video_filepath": object_key,
        "model": model_name,
        "reviewer_prompt": body.reviewer_prompt,
        "mock": True,
        "reasoning": body.reasoning,
    }


def _mock_embedding(text: str) -> list[float]:
    """Deterministic unit-length placeholder vector; meaningless for similarity, right-sized for vector(1024)."""
    value = sum(ord(char) for char in text) % 100 / 100.0 or 0.01
    return [round(1 / _EMBEDDING_DIMENSIONS**0.5, 6) * (1 + value / 10)] * _EMBEDDING_DIMENSIONS


@router.post("/incidents/evidence-embeddings")
async def evidence_embeddings(body: EvidenceEmbeddingsRequest) -> list[dict[str, object]]:
    """Mock of the agent's evidence-embeddings route: placeholder vectors for a revision's evidence items."""
    db = await _writer_module().get_db()
    if db is None:
        raise HTTPException(503, "incident database is not configured or unavailable")
    revision = await db.get_revision(body.revision_id)
    if revision is None:
        raise HTTPException(404, f"Revision {body.revision_id} not found")
    return [
        {
            "item_type": entry["item_type"],
            "item_id": entry["item_id"],
            "embedding": _mock_embedding(f"{entry.get('item_name')}: {entry.get('description')}"),
        }
        for entry in revision.get("evidence") or []
        if entry.get("item_type") and entry.get("item_id")
    ]
