"""Mirrors services/agent/src/vss_agents/api/rtsp_ingest.py and rtsp_delete.py.

Low priority: trivial canned success responses, no real RTSP handling.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from search_profile_mock.state import AppState
from search_profile_mock.state import Stream
from search_profile_mock.state import get_state

router = APIRouter(prefix="/api/v1/rtsp-streams")


class AddStreamRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sensor_url: str = Field(alias="sensorUrl")
    name: str
    username: str = ""
    password: str = ""
    location: str = ""
    tags: str = ""


class AddStreamResponse(BaseModel):
    model_config = ConfigDict(exclude_none=True)

    status: str
    message: str
    error: str | None = None


@router.post("/add")
async def add_rtsp_stream(body: AddStreamRequest, state: AppState = Depends(get_state)) -> AddStreamResponse:
    async with state.lock:
        state.streams[body.name] = Stream(
            stream_id=body.name,
            name=body.name,
            filename=body.sensor_url,
            bytes_total=0,
            stream_type="rtsp",
        )
    return AddStreamResponse(status="success", message=f"RTSP stream '{body.name}' added")


class DeleteStreamResponse(BaseModel):
    status: str
    message: str
    name: str


@router.delete("/delete/{name}")
async def delete_rtsp_stream(name: str, state: AppState = Depends(get_state)) -> DeleteStreamResponse:
    async with state.lock:
        existed = state.streams.pop(name, None) is not None
    status = "success" if existed else "partial"
    return DeleteStreamResponse(status=status, message=f"RTSP stream '{name}' removed", name=name)
