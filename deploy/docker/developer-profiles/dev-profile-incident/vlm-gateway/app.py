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

"""VLM Gateway - Thin proxy for NVIDIA-hosted OpenAI-compatible LLM/VLM inference.

This service holds the single real API credential server-side so that
browser-facing consumers (e.g., incident-console-v2 Next.js app) can call
LLM/VLM inference without exposing the key client-side.

Endpoint contract (mirrors base profile's remote-LLM/VLM contract):
- One API-key env var (VLM_GATEWAY_API_KEY)
- One endpoint-URL env var (VLM_GATEWAY_BASE_URL)
- OpenAI-compatible /v1/chat/completions
- Caller picks the model name via the request body's `model` field
- No model validation or defaulting - model-agnostic passthrough
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

app = FastAPI(title="VLM Gateway", version="0.1.0")


def _get_base_url() -> str:
    url = os.getenv("VLM_GATEWAY_BASE_URL", "https://switchyard-13doh4lsz.brevlab.com/v1")
    return url.rstrip("/")


def _get_api_key() -> str | None:
    key = os.getenv("VLM_GATEWAY_API_KEY")
    return key if key else None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """Forward OpenAI-compatible chat completions request to upstream.

    Reads the caller's JSON body verbatim, forwards it to the configured
    upstream endpoint with Authorization: Bearer <key> header added,
    and returns the upstream response verbatim (same status code and body).
    """
    base_url = _get_base_url()
    api_key = _get_api_key()

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="VLM_GATEWAY_API_KEY is not configured on the server",
        )

    try:
        body: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    upstream_url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            upstream_resp = await client.post(
                upstream_url,
                json=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream request failed: {type(exc).__name__}: {exc}",
            ) from exc

    # httpx transparently decodes compressed response bodies. Forwarding the
    # upstream content-length/content-encoding after that transformation makes
    # strict clients (including Node's fetch/undici) reject an otherwise valid
    # response with UND_ERR_RES_CONTENT_LENGTH_MISMATCH. Hop-by-hop headers are
    # likewise owned by this connection, not the upstream connection.
    excluded_headers = {
        "connection",
        "content-encoding",
        "content-length",
        "transfer-encoding",
    }
    response_headers = {
        key: value for key, value in upstream_resp.headers.items() if key.lower() not in excluded_headers
    }

    # Preserve application headers and status; Starlette calculates the
    # transport headers for the actual bytes returned below.
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
        media_type=upstream_resp.headers.get("content-type", "application/json"),
    )
