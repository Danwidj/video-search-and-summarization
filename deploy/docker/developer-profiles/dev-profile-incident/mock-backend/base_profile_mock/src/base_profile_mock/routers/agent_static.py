from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import Response

from base_profile_mock.state import AppState
from base_profile_mock.state import get_state

router = APIRouter(prefix="/static")


@router.get("/{filename}")
async def get_static_file(filename: str, state: AppState = Depends(get_state)) -> Response:
    async with state.lock:
        content = state.static_files.get(filename)
    if content is None:
        raise HTTPException(404, "not found")
    return Response(content=content, media_type="text/markdown")
