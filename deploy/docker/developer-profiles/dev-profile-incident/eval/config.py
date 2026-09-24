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

"""Environment-driven configuration for the incident console.

Every value degrades gracefully when unset so the app imports and renders
without live infrastructure (see README.md). Real values and where they come
from are documented in ``dev-profile-incident/.env``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load the committed profile-level placeholder .env explicitly (not via
# find_dotenv()), then the untracked .env.local with override so real secrets
# win. This avoids the accidental code-live pickup of incident-console/.env
# that the previous bare load_dotenv() + find_dotenv() caused.
#
# This file lives at dev-profile-incident/eval/ (same nesting depth as
# incident-console/ and incident-console-v2/), so one parent reaches this
# directory and a second reaches dev-profile-incident/.env; .env.local
# resolves next to this file (dev-profile-incident/eval/.env.local, a
# symlink to the shared ../.env.local - see eval/README.md).
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).with_name(".env.local"), override=True)

# Proposed defaults from the incident plan - NOT sourced from any team spec.
# TODO: confirm against team spec.
DEFAULT_SEVERITY_NOTIFY_THRESHOLD = 4
NOTIFICATION_GROUP_WINDOW_SECONDS = 300  # TODO: confirm against team spec.


def _clean(value: str | None) -> str:
    return (value or "").strip()


def incident_db_dsn() -> str:
    """SQLAlchemy sync URL for the incident Postgres. Empty string when unset."""
    return _clean(os.getenv("INCIDENT_DB_DSN"))


# How long a successful database round trip lets ``ui.get_db_or_notice`` skip its
# health probe (0 = probe on every page run). Any failed connection clears it early.
DEFAULT_DB_HEALTHCHECK_TTL_SECONDS = 15.0

# Pooled connections older than this are replaced at checkout (no round trip). The
# hosted pooler's idle limit is undocumented, so keep connections young; see
# README "Database connection".
DEFAULT_DB_POOL_RECYCLE_SECONDS = 600


def db_healthcheck_ttl_seconds() -> float:
    """``INCIDENT_DB_HEALTHCHECK_TTL_SECONDS``: seconds a good health check stays valid (0 disables)."""
    try:
        return max(0.0, float(_clean(os.getenv("INCIDENT_DB_HEALTHCHECK_TTL_SECONDS"))))
    except (TypeError, ValueError):
        return DEFAULT_DB_HEALTHCHECK_TTL_SECONDS


def db_pool_recycle_seconds() -> int:
    """``INCIDENT_DB_POOL_RECYCLE_SECONDS``: max age of a pooled connection (-1 never recycles)."""
    return _int_env("INCIDENT_DB_POOL_RECYCLE_SECONDS", DEFAULT_DB_POOL_RECYCLE_SECONDS)


def agent_base_url() -> str:
    """Base URL of vss-agent's upload + AI-trigger API."""
    return _clean(os.getenv("INCIDENT_AGENT_BASE_URL")) or "http://localhost:8000"


def llm_base_url() -> str:
    """OpenAI-compatible chat-completions base URL (mock server or real NIM)."""
    return _clean(os.getenv("INCIDENT_LLM_BASE_URL"))


def embedding_base_url() -> str:
    """OpenAI-compatible embeddings base URL, used by ``matching.py``."""
    return _clean(os.getenv("INCIDENT_EMBEDDING_BASE_URL"))


def incident_llm_api_key() -> str:
    """Optional bearer token for ``INCIDENT_LLM_BASE_URL``.

    Empty for the local, unauthenticated ``mock_llm_server.py`` (unchanged,
    existing behavior); a real remote endpoint needs a real key here, sent as
    ``Authorization: Bearer <key>`` only when non-empty.
    """
    return _clean(os.getenv("INCIDENT_LLM_API_KEY"))


def incident_judge_model() -> str:
    """Model name sent to ``INCIDENT_LLM_BASE_URL`` for LLM-as-a-judge scoring.

    Defaults to ``"incident-judge"`` (what ``mock_llm_server.py`` accepts, and
    ``eval_gt.judge_description_similarity``'s previous hardcoded value) so an
    unset env var is a no-op for existing local-dev setups; a real upstream
    endpoint needs its own real model name here instead.
    """
    return _clean(os.getenv("INCIDENT_JUDGE_MODEL")) or "incident-judge"


# Minimum cosine similarity for an accepted entity/instrument/asset match against
# ground truth (matching.py). A pairing the assignment solver produces below
# this score is discarded as "no match" (missed detection or false positive)
# rather than accepted - not spec-sourced, a conservative default pending
# calibration against the real embedding model.
MIN_MATCH_SIMILARITY = 0.75

# Tolerance (seconds) for GT-vs-model timestamp/duration comparisons in
# eval_gt.py. Plan default pending team confirmation. TODO: confirm.
EVAL_TIMESTAMP_TOLERANCE_SECONDS = 5


def video_base_url() -> str:
    """Public/presigned URL prefix that ``st.video`` plays back from."""
    return _clean(os.getenv("INCIDENT_VIDEO_BASE_URL"))


def _int_env(name: str, default: int) -> int:
    try:
        return int(_clean(os.getenv(name)))
    except (TypeError, ValueError):
        return default


def severity_notify_threshold() -> int:
    return _int_env("INCIDENT_SEVERITY_NOTIFY_THRESHOLD", DEFAULT_SEVERITY_NOTIFY_THRESHOLD)


def http_timeout_seconds() -> float:
    try:
        return float(_clean(os.getenv("INCIDENT_HTTP_TIMEOUT_SECONDS")))
    except (TypeError, ValueError):
        return 15.0
