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

"""A reviewer-confirmed fresh look at a video, kept apart from the stored report (off unless
``INCIDENT_VIDEO_CHECK_ENABLED`` is set).

The look is **blind**: the VLM gets the question and the clip, never the report's claim, because the project found the
model agrees with a name it is shown (decision 2026-11-01, one vision call carrying the report's name). A second,
text-only call compares the two accounts. Code writes the answer in labelled parts, so neither can pass for the other.
Nothing is stored: a look never changes a report, an evidence item or a citation.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import os
import time
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

import httpx

from vss_agents import incident_contract
from vss_agents.utils import grounded_chat

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

ENABLED_ENV = "INCIDENT_VIDEO_CHECK_ENABLED"
LOOK_PROMPT_ID = "chat/video-look"
COMPARE_PROMPT_ID = "chat/video-compare"
LOOK_TIMEOUT_SECONDS = 85.0
RELATIONS = ("agrees", "conflicts", "unrelated", "unclear")
COMPARE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relation", "note"],
    "properties": {"relation": {"type": "string", "enum": list(RELATIONS)}, "note": {"type": "string"}},
}


def enabled() -> bool:
    """Whether this agent may offer and run video checks. Off unless the setting says otherwise."""
    return (os.environ.get(ENABLED_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


class VideoCheckError(RuntimeError):
    """The look could not be made; ``reason`` is written for the reviewer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VideoLook:
    can_answer: bool
    observation: str


class VideoLooker(Protocol):
    model: str

    async def look(self, video_url: str, question: str) -> VideoLook: ...


@dataclass
class OpenAIVideoLooker:
    """One vision call on the clip's signed URL, in the request shape the analysis uses (``video_url`` content)."""

    model: str = field(default_factory=lambda: os.environ.get("VLM_NAME", "").strip())
    base_url: str = field(
        default_factory=lambda: os.environ.get("VLM_GATEWAY_BASE_URL") or os.environ.get("VLM_BASE_URL") or ""
    )
    api_key: str = field(
        default_factory=lambda: os.environ.get("VLM_GATEWAY_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    )
    timeout_seconds: float = LOOK_TIMEOUT_SECONDS
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient
    clock: Callable[[], float] = time.perf_counter
    last_usage: dict[str, Any] = field(default_factory=dict)

    def request_body(self, video_url: str, question: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": video_url}},
                        {"type": "text", "text": incident_contract.render_prompt(LOOK_PROMPT_ID, question=question)},
                    ],
                }
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": 512,
            "media_io_kwargs": incident_contract.p1_request()["media_io_kwargs"],
            "response_format": {"type": "json_object"},
        }

    async def look(self, video_url: str, question: str) -> VideoLook:
        if not self.base_url or not self.model:
            raise VideoCheckError("Video checking is not configured on this agent.")
        root = self.base_url.rstrip("/").removesuffix("/v1")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = self.clock()
        try:
            async with self.client_factory(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{root}/v1/chat/completions", json=self.request_body(video_url, question), headers=headers
                )
        except httpx.TimeoutException as exc:
            raise VideoCheckError("The video check timed out, so nothing was learned from the video.") from exc
        except httpx.HTTPError as exc:
            raise VideoCheckError("The video model could not be reached.") from exc
        if response.status_code == 429:
            raise VideoCheckError("The video model is busy (rate limited). Try again in a minute.")
        if response.status_code >= 400:
            raise VideoCheckError(f"The video model returned an error (HTTP {response.status_code}).")
        try:
            body = response.json()
            parsed = json.loads(body["choices"][0]["message"]["content"])
            look = VideoLook(can_answer=parsed["can_answer"], observation=parsed["observation"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise VideoCheckError("The video model's reply could not be read.") from exc
        if (
            not isinstance(look.can_answer, bool)
            or not isinstance(look.observation, str)
            or not look.observation.strip()
        ):
            raise VideoCheckError("The video model's reply could not be read.")
        self.last_usage = {**(body.get("usage") or {}), "elapsed_ms": round((self.clock() - started) * 1000.0, 1)}
        return VideoLook(can_answer=look.can_answer, observation=look.observation.strip())


async def compare(model: grounded_chat.ChatModel, question: str, stored: str, observation: str) -> tuple[str, str]:
    """How the fresh look relates to the stored account: ``(relation, note)``. A failed comparison is ``unclear``:
    the two accounts still stand on their own, for a reviewer to read."""
    messages = [
        {"role": "system", "content": incident_contract.prompt(COMPARE_PROMPT_ID)},
        {"role": "user", "content": f"QUESTION:\n{question}\n\nSTORED REPORT:\n{stored}\n\nFRESH LOOK:\n{observation}"},
    ]
    try:
        reply = await model.complete(messages, COMPARE_SCHEMA)
    except grounded_chat.ChatModelError:
        return "unclear", ""
    relation, note = reply.get("relation"), reply.get("note")
    if relation not in RELATIONS or not isinstance(note, str):
        return "unclear", ""
    return str(relation), note.strip()


def compose(stored: str, look: VideoLook, relation: str, note: str) -> str:
    """The answer in labelled parts. A conflict is only ever flagged for a person: neither account is corrected."""
    parts = [f"Stored report: {stored.strip()}", f"Video reanalysis: {look.observation}"]
    if not look.can_answer:
        return "\n\n".join(parts)
    if relation == "conflicts":
        parts.append(f"Discrepancy: {note or 'These accounts differ.'} This needs human review.")
    elif relation == "agrees":
        parts.append(f"The two agree{': ' + note if note else '.'}")
    elif relation == "unrelated" and note:
        parts.append(f"Not in the report: {note}")
    else:
        parts.append("A reviewer should compare these two accounts.")
    return "\n\n".join(parts)


def usage(*calls: Mapping[str, Any]) -> dict[str, Any]:
    """The calls of one check added up (numbers summed per key), with their count."""
    total: dict[str, Any] = {"calls": len(calls)}
    for call in calls:
        for key, value in call.items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + value
    return total
