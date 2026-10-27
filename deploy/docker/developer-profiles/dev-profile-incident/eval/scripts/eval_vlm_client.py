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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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

# Fixed rate-limit policy for P1, identical for every model and decided before any
# benchmark result (.docs/decisions.md 2026-10-02). Never tuned per model or run.
# Switchyard's shared limits seen in the smoke test: cosmos-3-super-reasoner 240
# requests/min, nemotron-3-nano-omni 30,000 tokens/min (one P1 call is about 6k
# prompt tokens plus up to 16,384 completion tokens).
# - inter_call_delay_s: at least this long between the end of one P1 attempt and
#   the start of the next, any model. With three models interleaved, each model is
#   called at most about once a minute, so one model stays under 30,000 tokens/min.
# - HTTP 429 only: retry the same request after cooldown_s (one rate-limit window),
#   or Retry-After when the server asks for longer, at most max_rate_limit_retries
#   times. Every other failure is final.
# Waiting is never part of the processing time (each attempt is timed on its own).
P1_RATE_LIMIT_POLICY = {
    "inter_call_delay_s": 20.0,
    "cooldown_s": 60.0,
    "max_rate_limit_retries": 2,
    "honor_retry_after": True,
}

MODELS = [
    "nvidia/cosmos-3-nano-reasoner",
    "nvidia/cosmos-3-super-reasoner",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
]

# The default client timeout is read from contracts/inference.json so eval and
# the shared inference specification cannot diverge.
DEFAULT_TIMEOUT: float = float(contract.load_inference()["models"][0]["timeout_seconds"])

# Client timeout for one P1 call, the same for every model: the console's per-model
# ``timeout_seconds`` from contracts/inference.json, so the benchmark cuts no model
# off earlier than the console would. Recorded in every result as ``p1_timeout_s``.
P1_TIMEOUT_SECONDS: float = DEFAULT_TIMEOUT


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
    # P1 processing time: one HTTP round trip, timed from immediately before the
    # request is sent to immediately after the full response body has arrived.
    # Parsing, validation and everything after it are outside. ``None`` when no
    # request was sent (missing API key).
    elapsed_s: float | None = None
    started_at: str | None = None
    finished_at: str | None = None
    # Why the call failed: rate_limited (HTTP 429), timeout, http_error (other
    # status >= 400), transport_error (no response), invalid_response (a 2xx that
    # is not a completion) or not_sent. ``None`` on success.
    failure_kind: str | None = None
    retry_after_s: float | None = None  # the server's Retry-After on a 429, in seconds


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def chat_completion(
    model: str,
    messages: list[dict],
    *,
    inference_config: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ChatResult:
    """One ``/v1/chat/completions`` call. Fails soft (``ok=False``), never raises."""
    base_url, api_key = gateway_credentials()
    if not api_key:
        return ChatResult(ok=False, error="VLM_GATEWAY_API_KEY is not configured", failure_kind="not_sent")
    config = {**FIXED_INFERENCE_CONFIG, **(inference_config or {})}
    payload = {"model": model, "messages": messages, **config}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/chat/completions"
    # Timed region: the request only. requests (non-streaming) has read the whole
    # body when post() returns, so the stop point includes the model's last token.
    started_at = _utc_now()
    started = time.perf_counter()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        timing = {"elapsed_s": time.perf_counter() - started, "started_at": started_at, "finished_at": _utc_now()}
        kind = "timeout" if isinstance(exc, requests.Timeout) else "transport_error"
        return ChatResult(ok=False, error=f"{type(exc).__name__}: {exc}", failure_kind=kind, **timing)
    timing = {"elapsed_s": time.perf_counter() - started, "started_at": started_at, "finished_at": _utc_now()}
    if resp.status_code >= 400:
        failure = {
            "failure_kind": "rate_limited" if resp.status_code == 429 else "http_error",
            "retry_after_s": _retry_after_seconds(getattr(resp, "headers", None)) if resp.status_code == 429 else None,
        }
    else:
        failure = {"failure_kind": "invalid_response"}

    try:
        body = resp.json()
    except ValueError:
        return ChatResult(
            ok=False, status_code=resp.status_code, error=f"non-JSON response: {resp.text[:500]}", **timing, **failure
        )

    if resp.status_code >= 400:
        raw = body if isinstance(body, dict) else {}
        return ChatResult(
            ok=False, status_code=resp.status_code, error=json.dumps(body)[:1000], raw=raw, **timing, **failure
        )

    # A 2xx whose body is not a completion (e.g. JSON ``null``, seen from the
    # gateway for an unfetchable video URL) is a failed call, not an empty answer.
    if not isinstance(body, dict) or not body.get("choices"):
        return ChatResult(
            ok=False, status_code=resp.status_code, error=f"no completion in response body: {json.dumps(body)[:500]}",
            **timing, **failure,
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
        **timing,
    )


def _retry_after_seconds(headers) -> float | None:
    """``Retry-After`` as seconds (delta-seconds or an HTTP date), or ``None``."""
    value = (headers or {}).get("Retry-After") if hasattr(headers, "get") else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def p1_request_config() -> dict:
    """Everything sent with a P1 call beyond model/messages (recorded in results)."""
    return {**FIXED_INFERENCE_CONFIG, **P1_INFERENCE_CONFIG, "response_format": contract.response_format()}


def analyze_video_with_p1(model: str, video_url: str, *, timeout: float = DEFAULT_TIMEOUT,
                          prompt_text: str | None = None) -> ChatResult:
    """One P1 call: the video (signed URL) first, then the prompt; schema enforced.

    ``prompt_text`` is a registry prompt for an experiment (``prompt_registry.prompt_text``);
    the default is the production contract prompt, byte for byte.
    """
    content = [
        {"type": "video_url", "video_url": {"url": video_url}},
        {"type": "text", "text": contract.extraction_prompt() if prompt_text is None else prompt_text},
    ]
    messages = [{"role": "user", "content": content}]
    return chat_completion(model, messages, inference_config=p1_request_config(), timeout=timeout)


@dataclass
class P1Outcome:
    """The final P1 attempt plus every attempt's record (rate-limit retries included)."""

    result: ChatResult
    attempts: list[dict]

    @property
    def rate_limit_retries(self) -> int:
        return len(self.attempts) - 1

    def summary(self) -> dict:
        return {
            "policy": dict(P1_RATE_LIMIT_POLICY),
            "attempt_count": len(self.attempts),
            "rate_limit_retries": self.rate_limit_retries,
            "rate_limit_rejections": [a["error"] for a in self.attempts if a["failure_kind"] == "rate_limited"],
            "final_attempt_ok": self.result.ok,
            "final_failure_kind": self.result.failure_kind,
            "total_wait_s": sum(a["wait_before_s"] for a in self.attempts),
            "attempts": self.attempts,
        }


class P1Pacer:
    """Enforces ``inter_call_delay_s`` between the end of one P1 attempt and the start of the next."""

    def __init__(self, *, sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self._sleep, self._monotonic = sleep, monotonic
        self._last_end: float | None = None

    def wait(self, minimum_s: float) -> float:
        """Sleep until ``minimum_s`` has passed since the previous attempt ended; returns the time slept."""
        if self._last_end is None:
            return 0.0
        remaining = minimum_s - (self._monotonic() - self._last_end)
        if remaining <= 0:
            return 0.0
        self._sleep(remaining)
        return remaining

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)

    def mark_end(self) -> None:
        self._last_end = self._monotonic()


DEFAULT_PACER = P1Pacer()


def analyze_video_with_p1_rate_limited(model: str, video_url: str, *, pacer: P1Pacer | None = None,
                                       prompt_text: str | None = None) -> P1Outcome:
    """P1 under ``P1_RATE_LIMIT_POLICY``: paced, and retried after a cooldown on HTTP 429 only.

    The request is the same on every attempt. Each attempt keeps its own timing, so
    the final attempt's ``elapsed_s`` is one round trip and never includes waiting.
    """
    if prompt_text is None:
        return rate_limited(lambda: analyze_video_with_p1(model, video_url), pacer=pacer)
    return rate_limited(lambda: analyze_video_with_p1(model, video_url, prompt_text=prompt_text), pacer=pacer)


def rate_limited(call: Callable[[], ChatResult], *, pacer: P1Pacer | None = None,
                 max_retries: int | None = None) -> P1Outcome:
    """Run ``call`` under ``P1_RATE_LIMIT_POLICY`` (the same policy for every arm of an experiment).

    ``max_retries`` may only lower the policy's retry count (an experiment's request cap); it never raises it.
    """
    pacer = pacer or DEFAULT_PACER
    retries = P1_RATE_LIMIT_POLICY["max_rate_limit_retries"]
    retries = retries if max_retries is None else max(0, min(retries, max_retries))
    policy = P1_RATE_LIMIT_POLICY
    attempts: list[dict] = []
    wait_s, wait_reason = 0.0, "pacing"
    while True:
        if wait_reason == "pacing":
            wait_s = pacer.wait(policy["inter_call_delay_s"])
        else:
            pacer.sleep(wait_s)
        result = call()
        pacer.mark_end()
        attempts.append({
            "attempt": len(attempts) + 1,
            "wait_before_s": round(wait_s, 3),
            "wait_reason": wait_reason if wait_s > 0 else None,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "elapsed_s": result.elapsed_s,
            "status_code": result.status_code,
            "ok": result.ok,
            "failure_kind": result.failure_kind,
            "retry_after_s": result.retry_after_s,
            "error": (result.error or "")[:500],
        })
        if result.failure_kind != "rate_limited" or len(attempts) > retries:
            return P1Outcome(result=result, attempts=attempts)
        wait_s = policy["cooldown_s"]
        if policy["honor_retry_after"] and result.retry_after_s is not None:
            wait_s = max(wait_s, result.retry_after_s)
        wait_reason = "rate_limit_cooldown"


def generate_report_with_rp1(
    model: str, structured_json: dict, *, inference_config: dict | None = None, timeout: float = DEFAULT_TIMEOUT
) -> ChatResult:
    """One RP1 call: text-only, the validated (derived) P1 JSON as the sole input."""
    prompt = contract.report_prompt_template().format(structured_incident_json=json.dumps(structured_json, indent=2))
    messages = [{"role": "user", "content": prompt}]
    return chat_completion(model, messages, inference_config=inference_config, timeout=timeout)
