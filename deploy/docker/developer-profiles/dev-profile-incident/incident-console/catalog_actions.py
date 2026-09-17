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

"""Pure orchestration helpers for incident video upload and analysis.

Kept import-light (no ``streamlit``) so tests can drive them directly against
the hermetic SQLite fixture without going through ``AppTest``, which cannot
drive ``st.dialog`` content or timed ``st.fragment`` reruns.
"""

from __future__ import annotations

import hashlib

from agent_client import AgentClient, Result
from db import IncidentDB

UNANALYZED_STATUS = "unanalyzed"


def derive_video_id(sensor_id: str) -> str:
    """Map the agent's ``sensor_id`` to a stable id that fits ``videos.id`` (``String(20)``).

    ``sensor_id`` is validated server-side against ``^[A-Za-z0-9._-]{1,128}$``
    (``services/agent/.../video_ingest.py``) and the local mock's own derived
    ids are already 23 characters (``sensor-`` + 16 hex) - both exceed the
    20-char column, so it cannot be used as ``videos.id`` directly. Hashing is
    deterministic: re-completing the same upload (or a retried ``/complete``
    call) maps to the same video row instead of creating a duplicate.
    """
    return "v" + hashlib.sha256(sensor_id.encode("utf-8")).hexdigest()[:19]


def upload_and_record(agent: AgentClient, db: IncidentDB, *, filename: str, content: bytes) -> Result:
    """Run the agent's 3-step upload, then record the video in Postgres.

    On failure (including ``not_implemented``) no ``videos`` row is created.
    On success ``Result.data`` is the new ``video_id``.
    """
    result = agent.upload_video(filename=filename, content=content)
    if not result.ok:
        return result
    data = result.data if isinstance(result.data, dict) else {}
    sensor_id = data.get("sensor_id")
    if not sensor_id:
        return Result(ok=False, error=f"upload succeeded but no sensor_id was returned: {result.data!r}")
    video_id = derive_video_id(sensor_id)
    # The current schema treats videos.filepath as the durable R2 object key.
    # Upload is too early to know the incident category, so analyze writes the
    # categorized key after it uploads the bytes to R2.
    db.upsert_video(video_id, filepath=None, source=sensor_id)
    return Result(ok=True, data=video_id, status_code=result.status_code)


def upload_and_analyze(
    agent: AgentClient, db: IncidentDB, *, filename: str, content: bytes, reasoning: bool = False
) -> Result:
    """Upload, create the video row, then immediately generate its report.

    ``upload_and_record`` deliberately writes the initial Supabase row with no
    filepath. The mock analyze endpoint then categorizes the upload, copies its
    bytes to R2, updates that filepath, and creates the incident/report rows.
    """
    uploaded = upload_and_record(agent, db, filename=filename, content=content)
    if not uploaded.ok:
        return uploaded

    video_id = uploaded.data
    analyzed = agent.analyze_incident(video_id, reasoning=reasoning)
    return Result(
        ok=analyzed.ok,
        data=video_id,
        error=analyzed.error,
        status_code=analyzed.status_code,
        not_implemented=analyzed.not_implemented,
    )


def current_status(db: IncidentDB, video_id: str) -> str:
    """The video's derived status, straight from a fresh DB read (see ``db.list_videos_with_counts``)."""
    rows = db.list_videos_with_counts()
    row = next((r for r in rows if r["id"] == video_id), None)
    return (row or {}).get("status", UNANALYZED_STATUS)


def should_keep_polling(status: str) -> bool:
    """Poll while a video has no incident recorded against it yet."""
    return status == UNANALYZED_STATUS
