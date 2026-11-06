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

"""``POST /api/v1/incidents/{video_id}/video-check`` - a reviewer's confirmed fresh look at the video.

Off unless ``INCIDENT_VIDEO_CHECK_ENABLED`` is set: a request is then a ``404``, and no model is called. It is reached
only from the console's "Check original video" action. It writes nothing: a look never changes a report or its evidence.
See :mod:`vss_agents.utils.video_check`.
"""

from __future__ import annotations

from collections.abc import Awaitable
from collections.abc import Callable
import logging
from typing import Any

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.utils import grounded_chat
from vss_agents.utils import incident_db
from vss_agents.utils import video_check
from vss_agents.utils.r2 import resolve_r2_url

logger = logging.getLogger(__name__)

VideoReader = Callable[[str], Awaitable[dict[str, Any] | None]]


class VideoCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=500)
    stored_answer: str = Field(..., min_length=1, max_length=4000, description="What the report-based answer said")


class VideoCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    source: str = "video"
    can_answer: bool
    relation: str
    model: str
    usage: dict[str, Any]


async def _read_video(video_id: str) -> dict[str, Any] | None:
    db = await incident_db.get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Incident database is not configured or unreachable")
    return await db.get_video(video_id)


def create_incident_video_check_router(
    looker: video_check.VideoLooker | None = None,
    chat_model: grounded_chat.ChatModel | None = None,
    read_video: VideoReader = _read_video,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/{video_id}/video-check",
        response_model=VideoCheckResponse,
        summary="A reviewer-confirmed fresh look at the original video, kept apart from the stored report",
        tags=["Incident Chat"],
    )
    async def check_video(video_id: str, body: VideoCheckRequest) -> VideoCheckResponse:
        if not video_check.enabled():
            raise HTTPException(status_code=404, detail="Video checks are not enabled on this agent")
        video = await read_video(video_id)
        if video is None or not video.get("filepath"):
            raise HTTPException(status_code=404, detail=f"The original video of {video_id} is not available")
        vision = looker if looker is not None else video_check.OpenAIVideoLooker()
        try:
            look = await vision.look(resolve_r2_url(str(video["filepath"])), body.question)
        except video_check.VideoCheckError as exc:
            logger.error("Video check failed for %s: %s", video_id, exc.reason)
            raise HTTPException(status_code=502, detail=exc.reason) from exc
        relation, note = "unclear", ""
        calls = [dict(getattr(vision, "last_usage", {}) or {})]
        if look.can_answer:
            text = chat_model if chat_model is not None else grounded_chat.OpenAIChatModel()
            relation, note = await video_check.compare(text, body.question, body.stored_answer, look.observation)
            calls.append(dict(getattr(text, "last_usage", {}) or {}))
        return VideoCheckResponse(
            content=video_check.compose(body.stored_answer, look, relation, note),
            can_answer=look.can_answer,
            relation=relation,
            model=vision.model,
            usage=video_check.usage(*calls),
        )

    return router


def register_incident_video_check_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/{video_id}/video-check`` onto the FastAPI app."""
    app.include_router(create_incident_video_check_router())
    logger.info("Registered POST /api/v1/incidents/{video_id}/video-check")
