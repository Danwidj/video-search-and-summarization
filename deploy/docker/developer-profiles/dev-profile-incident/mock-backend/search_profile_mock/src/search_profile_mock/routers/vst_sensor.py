from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from search_profile_mock.state import AppState
from search_profile_mock.state import Stream
from search_profile_mock.state import get_state

router = APIRouter(prefix="/vst/api/v1")


@router.get("/sensor/streams")
async def sensor_streams(request: Request, state: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    base = str(request.base_url).rstrip("/")
    async with state.lock:
        streams = list(state.streams.values())
    return [stream_entry(s, base) for s in streams]


def stream_entry(stream: Stream, base: str) -> dict[str, Any]:
    return {
        stream.stream_id: [
            {
                "name": stream.name,
                "url": f"{base}/vst/api/v1/storage/file/{stream.filename}",
                "isMain": True,
                "vodUrl": f"{base}/vst/api/v1/storage/file/{stream.filename}",
                "type": stream.stream_type,
                "storageLocation": f"/data/videos/{stream.filename}",
                "metadata": {"filename": stream.filename, "createdAt": stream.created_at},
            }
        ]
    }


class AddSensorRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sensor_url: str = Field(alias="sensorUrl")
    name: str
    username: str = ""
    password: str = ""
    location: str = ""
    tags: str = ""


@router.post("/sensor/add")
async def add_sensor(body: AddSensorRequest, state: AppState = Depends(get_state)) -> dict[str, str]:
    sensor_id = state.derive_sensor_id(body.sensor_url)
    async with state.lock:
        state.streams[sensor_id] = Stream(
            stream_id=sensor_id,
            name=body.name,
            filename=body.sensor_url,
            bytes_total=0,
            stream_type="rtsp",
        )
    return {"sensorId": sensor_id}


@router.delete("/sensor/{sensor_id}")
async def delete_sensor(sensor_id: str, state: AppState = Depends(get_state)) -> Response:
    async with state.lock:
        state.streams.pop(sensor_id, None)
    return Response(status_code=204)


@router.get("/sensor/version")
def sensor_version() -> dict[str, str]:
    return {"type": "vst", "version": "1.0.0-mock"}
