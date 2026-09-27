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

"""Thin client for the P1/RP1 multi-model evaluation, over ``vlm-gateway``'s
OpenAI-compatible ``/v1/chat/completions`` (the gateway itself, or directly
against its upstream switchyard endpoint - same contract either way).

P1 follows the shared incident contract (``dev-profile-incident/contracts/``,
``.docs/prompt-contract-plan.md``): one video as a signed R2 URL, placed before
the contract's extraction prompt, with the contract schema enforced through
``response_format`` - the same request shape the console and agent use. No
few-shot examples, no base64 inlining, no JSON extraction heuristics; the
response is parsed strictly by ``contract.parse_report``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contract  # noqa: E402

# Resolves to this eval project's own root (dev-profile-incident/eval/.env.local,
# a symlink to the shared ../.env.local - see eval/README.md), matching
# config.py's per-directory .env.local convention. (The original incident-console
# copy of this file used a fixed parents[3] depth that happened to land on a
# directory with no .env.local at all - _get_env() silently returned "" there
# and gateway_credentials() fell back entirely to the process environment.
# Anchoring on parents[1], this project's own root, is deliberate and stays
# correct regardless of how deeply this file is nested.)
ENV_LOCAL = Path(__file__).resolve().parents[1] / ".env.local"
DEFAULT_BASE_URL = "https://switchyard-13doh4lsz.brevlab.com/v1"

# Base configuration merged into every call (P1, RP1 and anything else that
# goes through chat_completion). temperature=0.0 for reproducibility.
FIXED_INFERENCE_CONFIG = {"temperature": 0.0, "max_tokens": 4096}

# The fixed P1 configuration, identical for every model and every video - never
# varied per model (see .docs/prompt-contract-plan.md §5a for the evidence):
# - max_tokens 16384: nemotron-3-nano-omni's reasoning exhausts 4096 before it
#   emits any JSON (finish_reason=length).
# - media_io_kwargs num_frames 64: the gateway otherwise samples ~24 frames per
#   video whatever its length. cosmos-3-super-reasoner ignores the setting and
#   stays at ~24; the other two honour it.
# response_format (the contract schema, strict) is added per call.
P1_INFERENCE_CONFIG = {"max_tokens": 16384, "media_io_kwargs": {"video": {"num_frames": 64}}}

MODELS = [
    "nvidia/cosmos-3-nano-reasoner",
    "nvidia/cosmos-3-super-reasoner",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]


def _get_env(key: str) -> str:
    if not ENV_LOCAL.exists():
        return ""
    for line in ENV_LOCAL.read_text(errors="replace").splitlines():
        line = line.rstrip("\r\n")
        if line.startswith(f"{key}="):
            return line[len(key) + 1 :]
    return ""


def gateway_credentials() -> tuple[str, str]:
    """``(base_url, api_key)`` from ``.env.local``, falling back to the process env."""
    api_key = _get_env("VLM_GATEWAY_API_KEY") or os.getenv("VLM_GATEWAY_API_KEY", "")
    base_url = _get_env("VLM_GATEWAY_BASE_URL") or os.getenv("VLM_GATEWAY_BASE_URL", "")
    return (base_url or DEFAULT_BASE_URL), api_key


@dataclass
class ChatResult:
    ok: bool
    content: str | None = None
    reasoning_content: str | None = None
    finish_reason: str | None = None
    raw: dict = field(default_factory=dict)
    error: str = ""
    status_code: int | None = None


def chat_completion(
    model: str,
    messages: list[dict],
    *,
    inference_config: dict | None = None,
    timeout: float = 240.0,
) -> ChatResult:
    """One ``/v1/chat/completions`` call. Fails soft (``ok=False``), never raises."""
    base_url, api_key = gateway_credentials()
    if not api_key:
        return ChatResult(ok=False, error="VLM_GATEWAY_API_KEY is not configured")
    config = {**FIXED_INFERENCE_CONFIG, **(inference_config or {})}
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, **config},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return ChatResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    try:
        body = resp.json()
    except ValueError:
        return ChatResult(ok=False, status_code=resp.status_code, error=f"non-JSON response: {resp.text[:500]}")

    if resp.status_code >= 400:
        raw = body if isinstance(body, dict) else {}
        return ChatResult(ok=False, status_code=resp.status_code, error=json.dumps(body)[:1000], raw=raw)

    # A 2xx whose body is not a completion (e.g. JSON ``null``, seen from the
    # gateway for an unfetchable video URL) is a failed call, not an empty answer.
    if not isinstance(body, dict) or not body.get("choices"):
        return ChatResult(
            ok=False, status_code=resp.status_code, error=f"no completion in response body: {json.dumps(body)[:500]}"
        )

    choice = body["choices"][0]
    message = choice.get("message", {})
    return ChatResult(
        ok=True,
        content=message.get("content"),
        reasoning_content=message.get("reasoning_content"),
        finish_reason=choice.get("finish_reason"),
        raw=body,
        status_code=resp.status_code,
    )


def p1_request_config() -> dict:
    """Everything sent with a P1 call beyond model/messages (recorded in results)."""
    return {**FIXED_INFERENCE_CONFIG, **P1_INFERENCE_CONFIG, "response_format": contract.response_format()}


def analyze_video_with_p1(model: str, video_url: str) -> ChatResult:
    """One P1 call: the video (signed URL) first, then the contract prompt; schema enforced."""
    content = [
        {"type": "video_url", "video_url": {"url": video_url}},
        {"type": "text", "text": contract.extraction_prompt()},
    ]
    messages = [{"role": "user", "content": content}]
    return chat_completion(model, messages, inference_config=p1_request_config())


def generate_report_with_rp1(model: str, structured_json: dict, *, inference_config: dict | None = None) -> ChatResult:
    """One RP1 call: text-only, the validated (derived) P1 JSON as the sole input."""
    prompt = contract.report_prompt_template().format(structured_incident_json=json.dumps(structured_json, indent=2))
    messages = [{"role": "user", "content": prompt}]
    return chat_completion(model, messages, inference_config=inference_config)
