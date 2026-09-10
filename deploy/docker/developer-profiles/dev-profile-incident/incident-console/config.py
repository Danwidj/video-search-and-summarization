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

# The committed dev-profile-incident/.env holds documented placeholders and is
# found by walking up from the process CWD. Real secrets (Supabase DSN, R2 keys)
# live in incident-console/.env.local, which is git-ignored (see
# incident-console/.gitignore) and loaded here with override so it wins over the
# placeholders. Missing files are ignored, so the app still runs with neither.
load_dotenv()
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


def agent_base_url() -> str:
    """Base URL of vss-agent's upload + AI-trigger API."""
    return _clean(os.getenv("INCIDENT_AGENT_BASE_URL")) or "http://localhost:8000"


def llm_base_url() -> str:
    """OpenAI-compatible chat-completions base URL (mock server or real NIM)."""
    return _clean(os.getenv("INCIDENT_LLM_BASE_URL"))


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
