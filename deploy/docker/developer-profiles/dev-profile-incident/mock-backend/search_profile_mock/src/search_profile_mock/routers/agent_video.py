"""Mirrors services/agent/src/vss_agents/api/video_ingest.py and video_delete.py."""

from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

from search_profile_mock.config import settings
from search_profile_mock.state import AppState
from search_profile_mock.state import get_state

router = APIRouter(prefix="/api/v1")

_SENSOR_ID_RE = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")


class VideoUploadUrlInput(BaseModel):
    filename: str = Field(min_length=1)


class VideoUploadUrlResponse(BaseModel):
    url: str


@router.post("/videos")
def create_video_upload_url(body: VideoUploadUrlInput) -> VideoUploadUrlResponse:
    if re.search(r"\s", body.filename):
        raise HTTPException(400, "Filename cannot contain whitespace. Please rename the file and try again.")
    base = settings.public_base_url.rstrip("/")
    return VideoUploadUrlResponse(url=f"{base}/vst/api/v1/storage/file")


class VideoUploadCompleteInput(BaseModel):
    filename: str | None = None
    custom_params: dict | None = None


class VideoIngestResponse(BaseModel):
    message: str
    sensor_id: str
    filename: str
    chunks_processed: int = 0


@router.post("/videos/{sensor_id}/complete")
async def complete_video_upload(
    sensor_id: str,
    body: VideoUploadCompleteInput,
    state: AppState = Depends(get_state),
) -> VideoIngestResponse:
    if not _SENSOR_ID_RE.match(sensor_id):
        raise HTTPException(400, "invalid sensor_id")

    async with state.lock:
        stream = state.streams.get(sensor_id)
        chunks_processed = 0
        filename = body.filename or (stream.filename if stream else sensor_id)
        for upload in state.uploads.values():
            if upload.sensor_id == sensor_id:
                chunks_processed = upload.chunks_received
                break

    return VideoIngestResponse(
        message="Video processing complete",
        sensor_id=sensor_id,
        filename=filename,
        chunks_processed=chunks_processed,
    )


class DeleteVideoResponse(BaseModel):
    status: str
    message: str
    video_id: str


@router.delete("/videos/{video_id}")
async def delete_video(video_id: str, state: AppState = Depends(get_state)) -> DeleteVideoResponse:
    async with state.lock:
        existed = state.streams.pop(video_id, None) is not None

    status = "success" if existed else "partial"
    return DeleteVideoResponse(
        status=status,
        message="Video deleted" if existed else "Video not found in mock catalog; treated as already deleted",
        video_id=video_id,
    )
