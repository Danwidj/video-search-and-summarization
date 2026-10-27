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

"""The pinned constants of ``evaluation-methodology-v1.0`` (``methodology/evaluation-methodology-v1.0.md``).

Every scoring instrument whose change would move a score is fixed here and recorded in
every result: the description judge (model, prompt file and its SHA-256, request
settings), the matching embedder, the thresholds and the bootstrap settings. A change
is a new methodology version, and results from different versions are never pooled.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

import config

METHODOLOGY_VERSION = "evaluation-methodology-v1.1"
METHODOLOGY_DIR = Path(__file__).resolve().parent / "methodology"

# Description and item-text judge (scores 0-1; a pass is >= DESCRIPTION_PASS_SCORE).
JUDGE_MODEL = "nvidia/nemotron-3-nano-30b-a3b"
JUDGE_PROMPT_VERSION = "judge-prompt-v1"
# v1.1: the judge's output is limited to 1,500 tokens (reasoning tokens included). A reply cut off at the
# limit (finish_reason "length"), one with no final content, or a score outside 0-1 is a scoring failure,
# never a score (eval_gt._judge_once).
JUDGE_MAX_OUTPUT_TOKENS = 1500
JUDGE_REQUEST_SETTINGS = {"temperature": 0.0, "max_tokens": JUDGE_MAX_OUTPUT_TOKENS}
DESCRIPTION_PASS_SCORE = 0.5
# Transient judge failures (network, timeout, HTTP 429/5xx) are retried with the identical request.
JUDGE_TRANSIENT_RETRIES = 2
JUDGE_RETRY_BACKOFF_SECONDS = (2.0, 8.0)

# Entity / instrument / asset matching.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_BASE_URL = "http://127.0.0.1:8811/v1"
MATCH_THRESHOLD = config.MIN_MATCH_SIMILARITY  # 0.75 cosine, one-to-one Hungarian assignment

# Incident fields.
TIMESTAMP_TOLERANCE_SECONDS = config.EVAL_TIMESTAMP_TOLERANCE_SECONDS  # +-5 s

# Uncertainty: 95% percentile intervals of a cluster bootstrap over videos.
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261027
BOOTSTRAP_CONFIDENCE = 0.95


@cache
def judge_prompt() -> str:
    return (METHODOLOGY_DIR / f"{JUDGE_PROMPT_VERSION}.txt").read_text()


def judge_prompt_sha256() -> str:
    return hashlib.sha256(judge_prompt().encode()).hexdigest()


def record() -> dict:
    """The pins, as written into every result file and aggregate."""
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "judge": {
            "model": JUDGE_MODEL,
            "prompt_version": JUDGE_PROMPT_VERSION,
            "prompt_sha256": judge_prompt_sha256(),
            "request_settings": dict(JUDGE_REQUEST_SETTINGS),
            "pass_score": DESCRIPTION_PASS_SCORE,
        },
        "embedding": {"model": EMBEDDING_MODEL, "base_url": EMBEDDING_BASE_URL},
        "match_threshold": MATCH_THRESHOLD,
        "timestamp_tolerance_s": TIMESTAMP_TOLERANCE_SECONDS,
        "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED, "confidence": BOOTSTRAP_CONFIDENCE},
    }


def judge_model_mismatch() -> str | None:
    """Why the configured judge differs from the pin, or ``None`` when it does not.

    ``INCIDENT_JUDGE_MODEL`` may be unset (the pin is used) or set to the pin. Anything else
    would score with a different instrument, so a run refuses to start.
    """
    configured = config.configured_judge_model()
    if configured and configured != JUDGE_MODEL:
        return f"INCIDENT_JUDGE_MODEL is {configured!r}, but {METHODOLOGY_VERSION} pins the judge to {JUDGE_MODEL!r}"
    return None
