"""Primary chat transport: WS /websocket - full HITL round-trip.

Message shapes mirror
services/ui/packages/nemo-agent-toolkit-ui/types/websocket.ts and the
outbound shapes the client builds in Chat.tsx. Every inbound-to-client
message MUST carry the request's conversation_id verbatim or the UI client
silently drops it (validateWebSocketMessageWithConversationId).

user_interaction_message replies carry no conversation_id at all, only
thread_id - so the HITL thread (state.hitl_threads) remembers the
conversation_id to stamp on replies.
"""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

from fastapi import APIRouter
from fastapi import Depends
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from search_profile_mock.config import settings
from search_profile_mock.state import AppState
from search_profile_mock.state import ConversationTurn
from search_profile_mock.state import HitlThread
from search_profile_mock.state import get_state
from search_profile_mock.templates import CANCEL_KEYWORD
from search_profile_mock.templates import HITL_VLM_PROMPT_TEMPLATE
from search_profile_mock.templates import build_agent_mode_search_answer
from search_profile_mock.templates import build_generic_answer
from search_profile_mock.templates import build_report_markdown
from search_profile_mock.templates import build_video_list_answer
from search_profile_mock.templates import classify_intent
from search_profile_mock.templates import report_filename

router = APIRouter()

_INTERMEDIATE_TOOL_NAMES = ("vlm_prompt_builder", "video_context_analyzer")


def _extract_text(content: dict[str, Any] | None) -> str:
    if not content:
        return ""
    messages = content.get("messages", [])
    for message in messages:
        parts = message.get("content")
        if isinstance(parts, str):
            return parts
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    return str(part.get("text", ""))
    return ""


async def _send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_json(payload)


async def _stream_answer(websocket: WebSocket, conversation_id: str, answer: str) -> None:
    chunk_size = max(1, len(answer) // 3 or len(answer))
    for i in range(0, len(answer), chunk_size):
        await _send(
            websocket,
            {
                "type": "system_response_message",
                "status": "in_progress",
                "conversation_id": conversation_id,
                "content": {"text": answer[i : i + chunk_size]},
            },
        )
        await asyncio.sleep(0.05)
    await _send(
        websocket,
        {
            "type": "system_response_message",
            "status": "complete",
            "conversation_id": conversation_id,
            "content": {"text": ""},
        },
    )


async def _prompt_and_wait(websocket: WebSocket, thread: HitlThread, prompt_text: str) -> str:
    await _send(
        websocket,
        {
            "type": "system_interaction_message",
            "conversation_id": thread.conversation_id,
            "thread_id": thread.thread_id,
            "content": {"input_type": "text", "text": prompt_text},
        },
    )
    return await thread.reply_queue.get()


async def _handle_report_flow(
    websocket: WebSocket,
    state: AppState,
    conversation_id: str,
    parent_id: str,
    streams: dict[str, Any],
) -> None:
    for tool_name in _INTERMEDIATE_TOOL_NAMES:
        await _send(
            websocket,
            {
                "type": "system_intermediate_message",
                "conversation_id": conversation_id,
                "content": {"name": tool_name, "payload": "running"},
            },
        )
        await asyncio.sleep(0.2)

    thread_id = str(uuid.uuid4())
    thread = HitlThread(thread_id=thread_id, conversation_id=conversation_id, parent_id=parent_id)
    async with state.lock:
        state.hitl_threads[thread_id] = thread

    try:
        reply = await _prompt_and_wait(websocket, thread, HITL_VLM_PROMPT_TEMPLATE)
        if reply.strip().lower() == CANCEL_KEYWORD:
            await _stream_answer(websocket, conversation_id, "Report generation cancelled.")
            return
        if reply.strip() != "":
            # Non-blank, non-cancel reply is treated as an edit: re-prompt once,
            # then proceed regardless of the second reply (approve-or-edit-once UX).
            reply2 = await _prompt_and_wait(websocket, thread, HITL_VLM_PROMPT_TEMPLATE)
            if reply2.strip().lower() == CANCEL_KEYWORD:
                await _stream_answer(websocket, conversation_id, "Report generation cancelled.")
                return
    finally:
        async with state.lock:
            state.hitl_threads.pop(thread_id, None)

    filename = report_filename()
    markdown = build_report_markdown(streams, conversation_id)
    async with state.lock:
        state.static_files[filename] = markdown.encode("utf-8")

    link = f"{settings.public_base_url.rstrip('/')}/static/{filename}"
    await _stream_answer(websocket, conversation_id, f"Report generation complete. View it here: {link}")


async def _handle_user_message(websocket: WebSocket, state: AppState, data: dict[str, Any]) -> None:
    conversation_id = data.get("conversation_id") or str(uuid.uuid4())
    parent_id = data.get("id") or str(uuid.uuid4())
    message_text = _extract_text(data.get("content"))

    async with state.lock:
        state.conversations.setdefault(conversation_id, []).append(ConversationTurn(role="user", text=message_text))
        streams = dict(state.streams)

    intent = classify_intent(message_text)
    if intent == "video_list":
        await _stream_answer(websocket, conversation_id, build_video_list_answer(streams))
        return
    if intent == "search":
        await _stream_answer(
            websocket,
            conversation_id,
            build_agent_mode_search_answer(streams, message_text, base_url=settings.public_base_url),
        )
        return
    if intent == "report":
        await _handle_report_flow(websocket, state, conversation_id, parent_id, streams)
        return
    await _stream_answer(websocket, conversation_id, build_generic_answer(message_text, streams))


async def _handle_interaction_reply(state: AppState, data: dict[str, Any]) -> None:
    thread_id = data.get("thread_id")
    text = _extract_text(data.get("content"))
    async with state.lock:
        thread = state.hitl_threads.get(thread_id) if thread_id else None
    if thread is not None:
        await thread.reply_queue.put(text)


@router.websocket("/websocket")
async def websocket_endpoint(websocket: WebSocket, state: AppState = Depends(get_state)) -> None:
    await websocket.accept()
    # Track in-flight per-message handler tasks so receiving the next inbound message
    # (in particular a user_interaction_message HITL reply) never blocks on a
    # still-running user_message handler, while keeping a reference alive so the
    # task isn't garbage-collected mid-flight.
    background_tasks: set[asyncio.Task] = set()
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "user_message":
                task = asyncio.create_task(_handle_user_message(websocket, state, data))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
            elif msg_type == "user_interaction_message":
                await _handle_interaction_reply(state, data)
            else:
                await _send(
                    websocket,
                    {
                        "type": "error",
                        "conversation_id": data.get("conversation_id", ""),
                        "content": {"text": f"unknown message type: {msg_type}"},
                    },
                )
    except WebSocketDisconnect:
        pass
