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

"""Small shared Streamlit helpers used by every page."""

from __future__ import annotations

import streamlit as st

import config
import db
from theme import apply_base_style, page_header


def bootstrap(title: str, subtitle: str = "") -> None:
    """Standard per-page setup: page config, theme, header."""
    st.set_page_config(page_title=f"{title} - Incident Console", layout="wide")
    apply_base_style()
    page_header(title, subtitle)


def get_db_or_notice() -> db.IncidentDB | None:
    """Return the DB handle, or render a visible degraded state and return None."""
    if not db.is_configured():
        st.info(
            "**Database not configured.** Set `INCIDENT_DB_DSN` in "
            "`dev-profile-incident/.env` to enable catalog / report / dashboard / "
            "eval data. The rest of the page still renders so it stays reviewable.",
            icon="🗄️",
        )
        return None
    handle = db.get_db()
    if handle is None:
        st.error(
            "`INCIDENT_DB_DSN` is set but the database could not be reached. "
            "Check the DSN / network. The page still renders below."
        )
        return None
    ok, detail = handle.healthcheck()
    if not ok:
        st.error(f"Database configured but unreachable: {detail}")
        return None
    return handle


def notifications_panel(handle: db.IncidentDB | None) -> None:
    """Sidebar badge + toast for unacknowledged high-severity notifications."""
    if handle is None:
        return
    try:
        pending = handle.list_notifications(only_unacknowledged=True)
    except Exception:  # noqa: BLE001
        return
    with st.sidebar:
        if pending:
            st.warning(f"{len(pending)} unacknowledged high-severity alert(s)", icon="🔔")
        else:
            st.caption("No pending alerts")
    if pending:
        top = pending[0]
        st.toast(
            f"High-severity report #{top.get('report_id')} (severity {top.get('severity')})",
            icon="🔔",
        )


def video_playback_url(video_row: dict) -> str | None:
    """Resolve a playback URL for ``st.video`` from the configured base + r2 key."""
    base = config.video_base_url()
    key = (video_row or {}).get("r2_key") or (video_row or {}).get("filename")
    if not key:
        return None
    if key.startswith(("http://", "https://")):
        return key
    if not base:
        return None
    return f"{base.rstrip('/')}/{key.lstrip('/')}"
