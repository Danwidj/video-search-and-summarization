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

import difflib
import hashlib
import re
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from incident_report import canned_incident_report, to_completion_payload

app = FastAPI(title="incident-console mock LLM", version="0.1.0")

# Fixed dimension for the deterministic hashed bag-of-words embedding below.
_EMBEDDING_DIM = 64

# A judge request is detected by model name or by a marker in its system
# prompt (see eval_gt.judge_description_similarity), never by guessing content.
_JUDGE_MODEL = "incident-judge"
_JUDGE_MARKER = "INCIDENT_JUDGE_REQUEST"

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class _Message(BaseModel):
    role: str
    content: Any = ""


class _ChatRequest(BaseModel):
    model: str = "mock-incident-llm"
    messages: list[_Message] = []
    stream: bool = False


class _EmbeddingsRequest(BaseModel):
    model: str = "embedding"
    input: list[str] = []


def _flatten(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _hashed_bow_vector(text: str, *, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Deterministic hashed bag-of-words vector: one bucket per token hash.

    No ML dependency beyond what ``matching.py`` already imports (``numpy`` for
    the cosine similarity matrix) - each token is hashed into one of ``dim``
    buckets and counted, giving real cosine separation: texts sharing most
    tokens land in mostly the same buckets and score high; unrelated texts
    score near zero.
    """
    vector = [0.0] * dim
    for token in re.findall(r"[a-z0-9']+", text.lower()):
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dim
        vector[bucket] += 1.0
    return vector


@app.post("/v1/embeddings")
def embeddings(req: _EmbeddingsRequest) -> dict:
    """OpenAI-compatible embeddings stub for ``matching.py`` / ``embed_client.py``."""
    return {
        "object": "list",
        "model": req.model,
        "data": [
            {"object": "embedding", "index": i, "embedding": _hashed_bow_vector(text)}
            for i, text in enumerate(req.input)
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def _is_judge_request(req: _ChatRequest) -> bool:
    if req.model == _JUDGE_MODEL:
        return True
    system_text = " ".join(_flatten(m.content) for m in req.messages if m.role == "system")
    return _JUDGE_MARKER in system_text


def _judge_similarity_score(req: _ChatRequest) -> dict:
    """Deterministic text-similarity heuristic standing in for an LLM judge.

    Blends a sequence-match ratio (rewards shared word order/substrings) with
    token Jaccard (rewards shared vocabulary regardless of order) so a
    reworded-but-equivalent description still scores high while unrelated text
    scores low.
    """
    user_text = " ".join(_flatten(m.content) for m in req.messages if m.role != "system")
    match = re.search(r"EXPECTED:\s*(.*?)\s*PREDICTED:\s*(.*)", user_text, re.DOTALL)
    expected, predicted = (match.group(1), match.group(2)) if match else ("", user_text)

    ratio = difflib.SequenceMatcher(None, expected.lower(), predicted.lower()).ratio()
    expected_tokens = set(re.findall(r"[a-z0-9']+", expected.lower()))
    predicted_tokens = set(re.findall(r"[a-z0-9']+", predicted.lower()))
    union = expected_tokens | predicted_tokens
    jaccard = len(expected_tokens & predicted_tokens) / len(union) if union else 0.0
    score = round((ratio + jaccard) / 2, 4)

    content = f'```json\n{{"score": {score}, "reasoning": "deterministic mock judge heuristic"}}\n```'
    return to_completion_payload_raw(content, model=req.model)


def to_completion_payload_raw(content: str, *, model: str) -> dict:
    """Like ``incident_report.to_completion_payload`` but for arbitrary text content."""
    return {
        "id": "chatcmpl-mock-judge",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/chat/completions")
def chat_completions(req: _ChatRequest) -> dict:
    """Canned ``IncidentReport`` completion, or a deterministic judge score."""
    if _is_judge_request(req):
        return _judge_similarity_score(req)
    prompt = " ".join(_flatten(m.content) for m in req.messages if m.role != "system")
    report = canned_incident_report(prompt)
    return to_completion_payload(report, model=req.model)
