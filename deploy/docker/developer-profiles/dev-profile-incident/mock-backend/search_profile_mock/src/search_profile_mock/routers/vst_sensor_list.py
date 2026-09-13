"""VST sensor-list surfaces the search tab's filter UI needs.

`GET /vst/api/v1/sensor/list` returns the flat
`[{name, sensorId, state, type}]` array consumed by
services/ui/packages/nv-metropolis-bp-vss-ui/search/lib-src/hooks/useFilter.ts
(and the shared `fetchSensorMap` helper in the alerts package) - online
sensors only. `GET /vst/api/v1/live/streams` returns the live-stream catalog
`[{name, url, streamId}]` from the same helper module. Both derive from the
same in-memory stream catalog as every other VST route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request

from search_profile_mock.state import AppState
from search_profile_mock.state import get_state

router = APIRouter(prefix="/vst/api/v1")


@router.get("/sensor/list")
async def sensor_list(state: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    async with state.lock:
        streams = list(state.streams.values())
    return [
        {
            "name": stream.name,
            "sensorId": stream.stream_id,
            "state": "online",
            "type": stream.stream_type,
        }
        for stream in streams
    ]


@router.get("/live/streams")
async def live_streams(request: Request, state: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    base = str(request.base_url).rstrip("/")
    async with state.lock:
        streams = list(state.streams.values())
    return [
        {
            "name": stream.name,
            "url": f"{base}/vst/api/v1/storage/file/{stream.filename}",
            "streamId": stream.stream_id,
        }
        for stream in streams
    ]
