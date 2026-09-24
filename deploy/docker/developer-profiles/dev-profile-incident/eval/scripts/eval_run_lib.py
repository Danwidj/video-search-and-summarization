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

"""Small shared helpers for ``eval_run.py`` - kept separate so they're testable
without pulling in the live VLM/DB calls ``eval_run.py`` itself makes.
"""

from __future__ import annotations


class EvaluatorDependencyError(RuntimeError):
    """The embedding server or LLM judge is unavailable or returned an invalid
    result. Raised to abort the whole batch run immediately - per the
    confirmed requirement, a dependency outage must fail/stop the run, never
    silently continue with missing/default scores treated as valid.
    """


def check_embedding_server_healthy(base_url: str, *, expected_model: str, timeout: float = 10.0) -> None:
    """Raises :class:`EvaluatorDependencyError` unless the embedding server is
    reachable and reports the exact frozen model - never proceeds silently on
    a different model or a degraded/unreachable server.

    ``base_url`` is the OpenAI-compatible embeddings prefix (e.g.
    ``http://host:port/v1``, matching what ``embed_client.py`` calls
    ``/embeddings`` on) - but ``eval_embedding_server.py`` serves ``/health``
    at the server root, not under ``/v1``, so that ``/v1`` suffix is stripped
    before appending ``/health``. Confirmed by direct reproduction: appending
    "/health" to the unstripped base_url 404s every time (hits "/v1/health",
    which doesn't exist) even though the server is healthy.
    """
    import httpx

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    try:
        resp = httpx.get(f"{root}/health", timeout=timeout)
    except httpx.HTTPError as exc:
        raise EvaluatorDependencyError(f"embedding server unreachable at {base_url}: {type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        raise EvaluatorDependencyError(f"embedding server health check returned HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    if body.get("model") != expected_model:
        raise EvaluatorDependencyError(
            f"embedding server is serving model {body.get('model')!r}, expected the frozen {expected_model!r}"
        )


def check_judge_ok(eval_result) -> None:
    """Raises :class:`EvaluatorDependencyError` if the LLM judge call for this
    video's incident description failed - a genuinely low similarity score is
    valid data; ``description_error`` non-empty means the call itself failed."""
    if eval_result.description_error:
        raise EvaluatorDependencyError(f"LLM judge call failed: {eval_result.description_error}")

# RP1 (report generation) uses one fixed model/config, identical regardless of
# which of the three P1 models produced the input JSON - RP1 is never part of
# the model comparison. Verified reachable and correctly budgeted (4096
# tokens) before use.
#
# chat_template_kwargs.enable_thinking=False: without it, this reasoning model
# (nemotron-3-nano-30b-a3b) reliably spends its entire max_tokens budget on
# internal chain-of-thought and returns empty `content` with the full
# scratchpad in `reasoning_content` instead (confirmed live:
# finish_reason="length", completion_tokens==max_tokens, len(content)==0).
# This is the same parameter this codebase already uses for nemotron-3 models
# elsewhere (services/agent/src/vss_agents/utils/reasoning_utils.py). With it
# set, the same requests return finish_reason="stop" with a complete,
# well-formed report in `content` using a few hundred tokens, not 4096.
RP1_MODEL = "nvidia/nemotron-3-nano-30b-a3b"
RP1_INFERENCE_CONFIG = {
    "temperature": 0.0,
    "max_tokens": 4096,
    "chat_template_kwargs": {"enable_thinking": False},
}

# gt_incidents.model_run_id is String(20) - full model names don't fit, so a
# short, explicit (never algorithmically-truncated) code per model.
_MODEL_RUN_ID_CODES = {
    "nvidia/cosmos-3-nano-reasoner": "P1-cosmos3nano",
    "nvidia/cosmos-3-super-reasoner": "P1-cosmos3super",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": "P1-nemo3omni",
}


def model_run_id_for(model: str) -> str:
    try:
        return _MODEL_RUN_ID_CODES[model]
    except KeyError:
        raise ValueError(
            f"no model_run_id code registered for {model!r} - add one to _MODEL_RUN_ID_CODES "
            "(model_run_id is a DB String(20) column, so it can't be derived automatically)"
        ) from None


def safe_model_id(model: str) -> str:
    """Filesystem-safe slug for result filenames - no length constraint, just no ``/``."""
    return model.replace("/", "_")


def coerce_int_or_none(value):
    """P1's raw JSON can legitimately emit an integer-schema field as a float
    (e.g. ``"duration": 6.0`` instead of ``6``) - real LLM output variance,
    not a bug in P1 or a prior run. PostgREST/Postgres reject a bare JSON
    float for an INTEGER column outright (confirmed live: "invalid input
    syntax for type integer: \"6.0\""), so this coerces before any DB write.
    The raw, uncoerced value is still what's persisted in the result JSON's
    ``prediction``/``p1_raw`` fields - only the DB write path is affected.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))  # handles a numeric string with a decimal point, e.g. "6.0"
    except (TypeError, ValueError):
        return None


def score_matches_summary(eval_result, kind: str) -> dict:
    """One kind's Step 7 shape: matches (with attribute_scores), unmatched, counts."""
    return {
        "matches": eval_result.matches.get(kind, []),
        "unmatched_model": eval_result.unmatched.get(kind, {}).get("model", []),
        "unmatched_gt": eval_result.unmatched.get(kind, {}).get("gt", []),
        "counts": eval_result.counts.get(kind, {}),
    }
