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

Deliberately not ``services/alert/vlm/vlm_client.py``: this evaluation sends
full local videos as base64 data URIs in a single-video, single-turn request
(confirmed the only reliable shape across all three models - see the plan's
Step 3 spike results), not that client's frame-sampling/``extra_body`` path,
which is built for a differently-deployed local NIM.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

# Resolves to this eval project's own root (incident-console-v2/eval/.env.local,
# a symlink - see eval/README.md), matching config.py's per-directory .env.local
# convention. (The original incident-console copy of this file used a fixed
# parents[3] depth that happened to land on a directory with no .env.local at
# all - _get_env() silently returned "" there and gateway_credentials() fell
# back entirely to the process environment. Anchoring on parents[1], this
# project's own root, is deliberate rather than depth-coincidental.)
ENV_LOCAL = Path(__file__).resolve().parents[1] / ".env.local"
DEFAULT_BASE_URL = "https://switchyard-13doh4lsz.brevlab.com/v1"

# The one fixed inference configuration, identical across all three models and
# every request - per the confirmed experimental design, this is never varied
# per model. temperature=0.0 for determinism/reproducibility (matches this
# codebase's existing convention for extraction tasks elsewhere);
# max_tokens=4096 matches the vss-agent's own existing default. No num_frames/
# pixel-bound params here - those are services/alert/vlm/vlm_client.py's
# locally-hosted-NIM frame-sampling knobs, not applicable to the full-video,
# single-request shape this evaluation sends through the gateway.
FIXED_INFERENCE_CONFIG = {"temperature": 0.0, "max_tokens": 4096}

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


def video_to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    mime_type = mime_type or "video/mp4"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return f"data:{mime_type};base64,{b64}"


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
        return ChatResult(ok=False, status_code=resp.status_code, error=json.dumps(body)[:1000], raw=body)

    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message", {})
    return ChatResult(
        ok=True,
        content=message.get("content"),
        reasoning_content=message.get("reasoning_content"),
        finish_reason=choice.get("finish_reason"),
        raw=body,
        status_code=resp.status_code,
    )


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_BARE_OBJECT = re.compile(r"(\{[\s\S]*\})")


def extract_json(text: str | None) -> dict | None:
    """Best-effort JSON object extraction from a model response.

    Tries the raw text first (P1 asks for JSON-only output), then a fenced
    code block, then the largest brace-delimited substring - mirroring
    ``eval_gt._extract_score``'s fenced/bare-JSON fallback shape.
    """
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (_JSON_BLOCK, _BARE_OBJECT):
        match = pattern.search(text)
        if not match:
            continue
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    return None


def analyze_video_with_p1(
    model: str,
    video_path: Path,
    p1_prompt: str,
    *,
    few_shot_block: str | None = None,
    inference_config: dict | None = None,
) -> ChatResult:
    """One P1 call: optional text-exemplar block + one video, single turn."""
    user_text = p1_prompt if not few_shot_block else f"{few_shot_block}\n\n{p1_prompt}"
    content = [
        {"type": "video_url", "video_url": {"url": video_to_data_url(video_path)}},
        {"type": "text", "text": user_text},
    ]
    messages = [{"role": "user", "content": content}]
    return chat_completion(model, messages, inference_config=inference_config)


def generate_report_with_rp1(model: str, rp1_prompt_template: str, structured_json: dict, *,
                              inference_config: dict | None = None) -> ChatResult:
    """One RP1 call: text-only, P1's structured JSON as the sole input."""
    prompt = rp1_prompt_template.format(structured_incident_json=json.dumps(structured_json, indent=2))
    messages = [{"role": "user", "content": prompt}]
    return chat_completion(model, messages, inference_config=inference_config)
