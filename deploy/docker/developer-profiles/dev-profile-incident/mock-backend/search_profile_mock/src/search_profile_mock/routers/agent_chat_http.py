"""HTTP/SSE chat transport - the secondary, non-HITL path.

HITL (human-in-the-loop report-generation prompts) only works over the
websocket transport in the real UI client, so a report request here returns
one synchronous canned "report complete" answer instead of running the
approve/edit/cancel round-trip.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
import time
from typing import Any
import uuid

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from search_profile_mock.config import settings
from search_profile_mock.state import AppState
from search_profile_mock.state import get_state
from search_profile_mock.templates import build_agent_mode_search_answer
from search_profile_mock.templates import build_generic_answer
from search_profile_mock.templates import build_report_markdown
from search_profile_mock.templates import build_video_list_answer
from search_profile_mock.templates import classify_intent
from search_profile_mock.templates import report_filename

router = APIRouter()


def _extract_latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return str(part.get("text", ""))
    return ""


async def _answer_for(message: str, state: AppState) -> str:
    intent = classify_intent(message)
    async with state.lock:
        streams = dict(state.streams)

    if intent == "video_list":
        return build_video_list_answer(streams)
    if intent == "search":
        # Agent-mode search via chat: the search tab parses the ```json
        # {"data": [...]}``` block out of this answer (agentResponseParser).
        return build_agent_mode_search_answer(streams, message, base_url=settings.public_base_url)
    if intent == "report":
        filename = report_filename()
        markdown = build_report_markdown(streams, conversation_id="http")
        async with state.lock:
            state.static_files[filename] = markdown.encode("utf-8")
        link = f"{settings.public_base_url.rstrip('/')}/static/{filename}"
        return f"Report generation complete (no HITL over HTTP/SSE). Report: {link}"
    return build_generic_answer(message, streams)


def _openai_completion(answer: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
    }


def _openai_chunk(delta: str, finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta} if delta else {},
                "finish_reason": finish_reason,
            }
        ],
    }


async def _sse_stream(answer: str) -> AsyncIterator[str]:
    chunk_size = max(1, len(answer) // 3 or len(answer))
    for i in range(0, len(answer), chunk_size):
        yield f"data: {json.dumps(_openai_chunk(answer[i : i + chunk_size]))}\n\n"
    yield f"data: {json.dumps(_openai_chunk('', finish_reason='stop'))}\n\n"
    yield "data: [DONE]\n\n"


async def _handle(request: Request, state: AppState, *, stream: bool):
    body = await request.json()
    messages = body.get("messages", []) if isinstance(body, dict) else []
    message = _extract_latest_user_text(messages)
    answer = await _answer_for(message, state)

    if stream:
        return StreamingResponse(_sse_stream(answer), media_type="text/event-stream")
    return JSONResponse(_openai_completion(answer))


@router.api_route("/chat", methods=["GET", "POST"])
async def chat(request: Request, state: AppState = Depends(get_state)):
    return await _handle(request, state, stream=False)


@router.api_route("/chat/stream", methods=["GET", "POST"])
async def chat_stream(request: Request, state: AppState = Depends(get_state)):
    return await _handle(request, state, stream=True)


@router.api_route("/generate", methods=["GET", "POST"])
async def generate(request: Request, state: AppState = Depends(get_state)):
    return await _handle(request, state, stream=False)


@router.api_route("/generate/stream", methods=["GET", "POST"])
async def generate_stream(request: Request, state: AppState = Depends(get_state)):
    return await _handle(request, state, stream=True)
