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

"""Pure orchestration helpers for the Catalog page's upload/analyze/poll actions.

Makes no ``st.*`` calls, so tests can drive them directly against the
hermetic SQLite fixture without going through ``AppTest``, which cannot
drive ``st.dialog`` content or timed ``st.fragment`` reruns. It is not
import-light: ``dashboard_data`` and ``r2_videos`` import ``streamlit`` at
module level.
"""

from __future__ import annotations

import hashlib

from agent_client import AgentClient, Result
from dashboard_data import clear_evidence_cache
from db import IncidentDB
from r2_videos import download_video_bytes

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
    db.upsert_video(video_id, filepath=data.get("filepath"), source=sensor_id)
    return Result(ok=True, data=video_id, status_code=result.status_code)


def analyze_and_refresh(agent: AgentClient, video_id: str) -> Result:
    """Ask the agent to analyze ``video_id``, then drop the dashboard's cached evidence.

    The agent rewrites the incident's model-output rows (``incidents`` /
    ``entities`` / ``instruments`` / ``assets``) in its own process, so the
    console's cached dashboard evidence cannot notice. Clear it whether or not the
    call reported success: a failed run may still have written some rows.
    """
    try:
        return agent.analyze_incident(video_id)
    finally:
        clear_evidence_cache()


def current_status(db: IncidentDB, video_id: str) -> str:
    """The video's derived status, straight from a fresh DB read (see ``db.list_videos_with_counts``)."""
    rows = db.list_videos_with_counts()
    row = next((r for r in rows if r["id"] == video_id), None)
    return (row or {}).get("status", UNANALYZED_STATUS)


def should_keep_polling(status: str) -> bool:
    """Poll while a video has no incident recorded against it yet."""
    return status == UNANALYZED_STATUS


def ensure_video_registered(agent: AgentClient, db: IncidentDB, video_id: str) -> Result:
    """Ensure a video is registered with VST (has a sensor_id in ``videos.source``).

    If the video already has a source, returns it immediately.
    If the video has a filepath (R2 object key) but no source, downloads the video
    from R2 and runs the 3-step upload flow against VST, then persists the
    returned sensor_id to ``videos.source``. This is a one-time self-heal per row.

    Returns a Result with the sensor_id on success, or an error if:
    - The video row doesn't exist
    - The video has no filepath (SYN- rows with no recoverable bytes)
    - R2 download fails
    - VST upload fails
    """
    video = db.get_video(video_id)
    if not video:
        return Result(ok=False, error=f"Video {video_id!r} not found in catalog")

    existing_source = video.get("source")
    if existing_source:
        return Result(ok=True, data=existing_source)

    filepath = video.get("filepath")
    if not filepath:
        return Result(
            ok=False,
            error=(
                f"Video {video_id!r} has no VST registration and no recoverable video file in R2. "
                "This appears to be a synthetic placeholder (SYN-) row that cannot be analyzed."
            ),
        )

    # Download video bytes from R2
    content = download_video_bytes(filepath)
    if content is None:
        return Result(
            ok=False,
            error=f"Failed to download video from R2 for {video_id!r} (key: {filepath!r}). "
            "Check R2 configuration and that the object exists.",
        )

    # Upload to VST via the agent's 3-step upload flow
    filename = filepath.rsplit("/", 1)[-1]
    upload_result = agent.upload_video(filename=filename, content=content)
    if not upload_result.ok:
        return Result(
            ok=False,
            error=f"Self-heal upload to VST failed for {video_id!r}: {upload_result.error}",
        )

    data = upload_result.data if isinstance(upload_result.data, dict) else {}
    sensor_id = data.get("sensor_id")
    if not sensor_id:
        return Result(ok=False, error=f"Self-heal upload succeeded but no sensor_id returned: {upload_result.data!r}")

    # Persist the sensor_id to videos.source so this is a one-time self-heal
    # Preserve existing duration from the video row
    duration = video.get("duration")
    db.upsert_video(video_id, filepath=filepath, duration=duration, source=sensor_id)

    return Result(ok=True, data=sensor_id, status_code=upload_result.status_code)
