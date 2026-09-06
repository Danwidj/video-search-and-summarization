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

"""Incident console - entry point and navigation home.

Screens live under ``pages/`` (Streamlit multipage auto-nav):

* ``1_Catalog`` - video catalog, upload, metadata edit
* ``2_Report_Review`` - report review / verify / edit / jump-to-timestamp
* ``3_Dashboard`` - filters + aggregate insights
* ``4_Severity_Eval`` - human-vs-AI severity evaluation

Run locally with ``uv run streamlit run app.py`` - no Docker, no GPU, no live
backend required (see README.md). Everything degrades gracefully when the
database or agent is not configured.
"""

from __future__ import annotations

import streamlit as st

import config
import db
from theme import apply_base_style, page_header

st.set_page_config(
    page_title="Incident Console - VSS",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_base_style()
page_header(
    "Incident Console",
    "Video-driven incident search & reporting - NVIDIA VSS capstone",
)

st.markdown(
    """
    This console migrates the rise-up incident front-end onto the VSS blueprint.
    Use the pages in the sidebar:

    | Page | What it does |
    |---|---|
    | **Catalog** | Browse / search ingested videos, upload new footage, correct metadata |
    | **Report Review** | Review generated reports, verify, edit fields, jump to the incident timestamp |
    | **Dashboard** | Filter verified reports and read aggregate insights |
    | **Severity Eval** | Rate severity independently and compare against the AI |
    """
)

st.divider()
st.subheader("Environment")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Database (direct Postgres)**")
    if not db.is_configured():
        st.warning(
            "`INCIDENT_DB_DSN` is not set - catalog / review / dashboard / eval "
            "run in a read-only *database not configured* state. Set it in "
            "`dev-profile-incident/.env` to enable writes.",
            icon="⚠️",
        )
    else:
        handle = db.get_db()
        if handle is None:
            st.error("`INCIDENT_DB_DSN` is set but the engine could not be built. Check the DSN.")
        else:
            ok, detail = handle.healthcheck()
            if ok:
                st.success("Connected. Schema ensured via `CREATE TABLE IF NOT EXISTS`.", icon="✅")
            else:
                st.error(f"Configured but unreachable: {detail}")

with col2:
    st.markdown("**Agent / AI-trigger API**")
    st.write(f"Agent base URL: `{config.agent_base_url()}`")
    st.write(f"LLM base URL: `{config.llm_base_url() or '(unset)'}`")
    st.caption(
        "`POST /api/v1/incidents/{id}/analyze` and `POST /api/v1/search` are "
        "follow-up work - the client calls them against the plan's contract and "
        "fails soft (shows a notice) when they are absent. The mock LLM "
        "(`mock_llm_server.py`) covers the direct chat-completions path."
    )

st.divider()
st.caption(
    "Defaults for severity notification / eval thresholds and the incident "
    "taxonomy are plan proposals, not team spec - see `# TODO: confirm against "
    "team spec` markers in the source."
)
