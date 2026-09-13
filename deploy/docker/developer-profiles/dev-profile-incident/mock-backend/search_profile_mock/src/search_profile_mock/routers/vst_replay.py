from __future__ import annotations

from importlib import resources
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import Response

from search_profile_mock.routers.vst_sensor import stream_entry
from search_profile_mock.state import AppState
from search_profile_mock.state import get_state

router = APIRouter(prefix="/vst/api/v1")

_PLACEHOLDER_BYTES = (resources.files("search_profile_mock") / "assets" / "placeholder.jpg").read_bytes()


@router.get("/replay/streams")
async def replay_streams(request: Request, state: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    base = str(request.base_url).rstrip("/")
    async with state.lock:
        streams = list(state.streams.values())
    return [stream_entry(s, base) for s in streams]


@router.get("/live/stream/{stream_id}/picture")
def live_picture(stream_id: str) -> Response:  # noqa: ARG001 - path param required by the UI's URL contract, unused by this static mock
    return Response(content=_PLACEHOLDER_BYTES, media_type="image/jpeg")


@router.get("/replay/stream/{stream_id}/picture")
def replay_picture(
    stream_id: str,  # noqa: ARG001 - path param required by the UI's URL contract, unused by this static mock
    startTime: str | None = None,  # noqa: N803, ARG001 - query param name/presence is the UI's contract, unused by this static mock
) -> Response:
    return Response(content=_PLACEHOLDER_BYTES, media_type="image/jpeg")
