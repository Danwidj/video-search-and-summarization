"""Search-agent endpoints: the search profile's superset over base.

Mirrors the `endpoints:` block in
deploy/docker/developer-profiles/dev-profile-search/vss-agent/configs/config.yml
(`POST /api/v1/search`, `/api/v1/attribute_search`, `/api/v1/embed_search`,
`/api/v1/critic`) plus the deprecated compat shim in
services/agent/src/vss_agents/api/video_search_ingest.py
(`PUT /api/v1/videos-for-search/{filename}`).

Request field names mirror what the search tab actually posts - see
services/ui/packages/nv-metropolis-bp-vss-ui/search/lib-src/hooks/useSearch.ts
(snake_case full body, or the agent-mode `{agent_mode, query, top_k,
source_type}` variant). Results are canned derivations of the in-memory
stream catalog (see templates.build_search_results): uploading a video via
the base routes first is what makes search return hits.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel

from search_profile_mock.config import settings
from search_profile_mock.state import AppState
from search_profile_mock.state import Stream
from search_profile_mock.state import get_state
from search_profile_mock.templates import build_search_results

router = APIRouter(prefix="/api/v1")

_ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/x-matroska",
}


def _search_params(body: dict[str, Any]) -> dict[str, Any]:
    """Accept both the full search-tab body and the agent-mode variant."""
    query = body.get("query", "") or ""
    top_k = body.get("top_k", body.get("topK", 10))
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 10
    similarity = body.get("min_cosine_similarity", body.get("similarity", 0.0))
    try:
        min_similarity = float(similarity)
    except (TypeError, ValueError):
        min_similarity = 0.0
    video_sources = body.get("video_sources", body.get("videoSources") or [])
    return {
        "query": str(query),
        "top_k": top_k,
        "min_similarity": min_similarity,
        "video_sources": list(video_sources) if isinstance(video_sources, list) else [],
    }


async def _results_for(body: dict[str, Any], state: AppState) -> list[dict[str, Any]]:
    params = _search_params(body)
    async with state.lock:
        streams = dict(state.streams)
    return build_search_results(
        streams,
        params["query"],
        top_k=params["top_k"],
        base_url=settings.public_base_url,
        min_similarity=params["min_similarity"],
        video_sources=params["video_sources"],
    )


@router.post("/search")
async def text_search(request: Request, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Visual/text search over the mock embedding index (the stream catalog)."""
    body = await request.json()
    return {"data": await _results_for(body if isinstance(body, dict) else {}, state)}


@router.post("/embed_search")
async def direct_embed_search(request: Request, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Direct embedding search bypassing the agent (mock-shaped output).

    The real endpoint returns the embed tool's output; the UI never calls
    this directly (only the agent does), so the embedding vector here is a
    stub and `results` reuses the canned search-item shape.
    """
    body = await request.json()
    results = await _results_for(body if isinstance(body, dict) else {}, state)
    return {"query_embedding": [0.0] * 8, "results": results}


@router.post("/attribute_search")
async def attribute_search(request: Request, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Object-attribute search (mock: same canned items, attribute-flavored query)."""
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    attributes = body.get("attributes") or body.get("object_type") or body.get("query") or ""
    body = {**body, "query": f"attribute:{attributes}" if attributes else ""}
    return {"data": await _results_for(body, state)}


@router.post("/critic")
async def critic_score(request: Request, state: AppState = Depends(get_state)) -> dict[str, Any]:  # noqa: ARG001 - request body shape is the contract; scoring is canned
    """Critic-agent scoring stub: every clip verdict is `unverified`.

    The request body is accepted but not interpreted - there is no real
    critic model behind this mock.
    """
    body = await request.json()
    clips = body.get("clips", []) if isinstance(body, dict) else []
    results = [{"clip": clip, "result": "unverified", "criteria_met": {}} for clip in clips if isinstance(clip, dict)]
    return {"results": results, "note": "canned verdicts from the search-profile mock backend"}


class VideosForSearchResponse(BaseModel):
    message: str
    sensor_id: str
    filename: str
    chunks_processed: int = 0


@router.put("/videos-for-search/{filename}", deprecated=True)
async def upload_video_for_search(
    filename: str,
    request: Request,
    state: AppState = Depends(get_state),
) -> VideosForSearchResponse:
    """Deprecated single-request PUT upload (compat shim for CI fixtures).

    Mirrors services/agent/src/vss_agents/api/video_search_ingest.py:
    same Content-Type/Content-Length validation, then registers the stream
    directly instead of proxying to VST + RTVI. New callers should use the
    universal three-step flow (`POST /api/v1/videos` ...).
    """
    content_type = request.headers.get("content-type")
    content_length = request.headers.get("content-length")
    if not content_type:
        raise HTTPException(400, "Content-Type header is required (video/mp4 or video/x-matroska).")
    if content_type not in _ALLOWED_VIDEO_TYPES:
        raise HTTPException(415, f"Unsupported video format: {content_type}.")
    if not content_length:
        raise HTTPException(400, "Content-Length header is required.")
    try:
        size = int(content_length)
    except ValueError as exc:
        raise HTTPException(400, "Invalid Content-Length header.") from exc
    if size == 0:
        raise HTTPException(400, "File is empty.")

    body = await request.body()
    sensor_id = state.derive_sensor_id(f"videos-for-search:{filename}")
    async with state.lock:
        state.streams[sensor_id] = Stream(
            stream_id=sensor_id,
            name=filename,
            filename=filename,
            bytes_total=len(body),
        )
    return VideosForSearchResponse(
        message="Video processing complete",
        sensor_id=sensor_id,
        filename=filename,
        chunks_processed=1,
    )
