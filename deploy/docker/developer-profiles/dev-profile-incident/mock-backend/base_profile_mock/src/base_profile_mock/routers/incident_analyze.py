# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock incident analysis endpoint backed by the shared async incident writer."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import sys
import uuid

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel

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
        "type": "fighting",
        "folder": "fighting",
        "description": "MOCK incident report: two people are involved in a physical altercation.",
        "severity": 3,
        "confidence": 0.91,
    },
    {
        "type": "animal",
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


class AnalyzeRequest(BaseModel):
    reasoning: bool = False


def _writer_module():
    root = Path(__file__).resolve().parents[9] / "services" / "agent" / "src"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from vss_agents.utils import incident_db

    return incident_db


def _mock_category(incident_id: str) -> dict[str, object]:
    digest = hashlib.sha256(incident_id.encode("utf-8")).digest()
    return _MOCK_CATEGORIES[digest[0] % len(_MOCK_CATEGORIES)]


def _safe_filename(filename: str, incident_id: str) -> str:
    name = PurePosixPath(filename or f"{incident_id}.mp4").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not cleaned:
        cleaned = f"{incident_id}.mp4"
    if "." not in cleaned:
        cleaned = f"{cleaned}.mp4"
    return cleaned


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
    filename = _safe_filename(stream.filename, incident_id)
    key = f"anomaly/{category['folder']}/{filename}"
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
    R2 before the incident/report rows are written.
    """
    if not incident_id or len(incident_id) > 20:
        raise HTTPException(400, "invalid video id")
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
        model_run_id = "mock-run-" + uuid.uuid4().hex[:11]
        report_id = "mock-rpt-" + uuid.uuid4().hex[:10]
        async with db.transaction() as tx:
            await tx.update_video(incident_id, filepath=object_key)
            await tx.insert_model_run(
                model_run_id,
                model_name="base-profile-mock",
                model_version="mock-v1",
                prompt_version="mock-incident-v1",
                notes="MOCK output generated by base_profile_mock; no VSS inference was run.",
            )
            await tx.insert_incident(
                incident_id,
                model_run_id,
                fields={
                    "type": category["type"],
                    "start_timestamp": "00:00:00",
                    "end_timestamp": "00:00:10",
                    "duration": 10,
                    "description": category["description"],
                    "severity_level": category["severity"],
                    "confidence_score": category["confidence"],
                },
            )
            await tx.add_incident_entity(
                incident_id,
                model_run_id,
                entity_id="person-1",
                type="human",
                description="MOCK detected person involved in the incident.",
            )
            await tx.insert_generated_report(
                report_id,
                incident_id=incident_id,
                model_run_id=model_run_id,
                filepath=f"mock://reports/{report_id}.md",
            )
    return {
        "status": "completed",
        "video_id": incident_id,
        "model_run_id": model_run_id,
        "report_id": report_id,
        "incident_type": category["type"],
        "video_filepath": object_key,
        "mock": True,
        "reasoning": body.reasoning,
    }
