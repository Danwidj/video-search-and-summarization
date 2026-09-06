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

"""Tiny OpenAI-compatible mock LLM for local incident-console iteration.

Local-dev only - never deployed to the VM. It lets the real route ->
tool-calling -> schema-extraction -> Postgres-write path be exercised with zero
GPU / NIM / Elasticsearch, per incident-plan-implementation-local.md S2.

Run it with::

    uv run uvicorn mock_llm_server:app --port 8900

Then point ``INCIDENT_LLM_BASE_URL`` (and, for the real agent, its
``LLM_BASE_URL`` / ``VLM_BASE_URL``) at ``http://localhost:8900/v1``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from incident_report import canned_incident_report, to_completion_payload

app = FastAPI(title="incident-console mock LLM", version="0.1.0")


class _Message(BaseModel):
    role: str
    content: Any = ""


class _ChatRequest(BaseModel):
    model: str = "mock-incident-llm"
    messages: list[_Message] = []
    stream: bool = False


def _flatten(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
def chat_completions(req: _ChatRequest) -> dict:
    """Return a canned completion whose content is an IncidentReport JSON blob."""
    prompt = " ".join(_flatten(m.content) for m in req.messages if m.role != "system")
    report = canned_incident_report(prompt)
    return to_completion_payload(report, model=req.model)
