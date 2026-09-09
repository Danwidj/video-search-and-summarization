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

"""Catalog: browse / search ingested videos, upload footage, correct metadata."""

from __future__ import annotations

import pandas as pd
import streamlit as st


import config
from agent_client import AgentClient
from incident_report import VIDEO_STATUSES, canned_incident_report
from ui import bootstrap, get_db_or_notice, notifications_panel

bootstrap("Catalog", "Ingested video library, upload, and metadata correction")

handle = get_db_or_notice()
notifications_panel(handle)
agent = AgentClient()

# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
st.subheader("Upload footage")
st.caption(
    "Calls vss-agent's profile-agnostic `POST /api/v1/videos` upload contract "
    f"(`{config.agent_base_url()}`), then records a catalog row. Container "
    "validation (mp4/mkv) is surfaced from VIOS."
)
uploaded = st.file_uploader("Choose a video file", type=["mp4", "mkv"])
if uploaded is not None:
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.info(f"Ready: `{uploaded.name}` ({uploaded.size / 1_048_576:.1f} MiB)")
    with col_b:
        go = st.button("Upload", type="primary", width="stretch")
    offline = st.checkbox(
        "Add a catalog row even if the agent upload fails (local review)",
        value=True,
    )
    if go:
        result = agent.upload_video(filename=uploaded.name, content=uploaded.getvalue())
        sensor_id = None
        if result.ok:
            sensor_id = (result.data or {}).get("sensor_id")
            st.success(f"Agent accepted upload. sensor_id=`{sensor_id}`")
        else:
            st.warning(f"Agent upload did not complete: {result.error}")
        if handle is None:
            st.info("No database configured - nothing recorded.")
        elif result.ok or offline:
            new_id = handle.insert_video(
                filename=uploaded.name,
                r2_key=uploaded.name,
                sensor_id=sensor_id,
                status="unanalyzed",
            )
            st.success(f"Catalog row #{new_id} created (status `unanalyzed`).")

st.divider()

# --------------------------------------------------------------------------- #
# Catalog list
# --------------------------------------------------------------------------- #
st.subheader("Catalog")
f1, f2 = st.columns([3, 1])
with f1:
    name_q = st.text_input("Search filename", placeholder="clip name fragment...").strip()
with f2:
    status_q = st.selectbox("Status", ["All", *VIDEO_STATUSES])

rows: list[dict] = []
if handle is not None:
    rows = handle.list_videos(filename_like=name_q or None, status=status_q)

if not rows:
    st.caption("No videos to show." if handle is not None else "Connect a database to list videos.")
else:
    df = pd.DataFrame(rows)
    show_cols = [c for c in ["id", "filename", "status", "location", "camera_source", "uploaded_at"] if c in df.columns]
    st.dataframe(df[show_cols], hide_index=True, width="stretch")
    st.write(f"{len(rows)} video(s).")

# --------------------------------------------------------------------------- #
# Metadata edit + analyze trigger
# --------------------------------------------------------------------------- #
if rows:
    st.divider()
    st.subheader("Edit metadata / trigger analysis")
    by_id = {r["id"]: r for r in rows}
    picked = st.selectbox(
        "Video",
        options=list(by_id),
        format_func=lambda i: f"#{i} - {by_id[i]['filename']}",
    )
    video = by_id[picked]

    with st.form("edit_video_meta"):
        location = st.text_input("Location", value=video.get("location") or "")
        camera = st.text_input("Camera source", value=video.get("camera_source") or "")
        editor = st.text_input("Edited by", value="", placeholder="your name (freeform)")
        saved = st.form_submit_button("Save metadata", type="primary")
    if saved:
        if handle is None:
            st.error("No database configured.")
        elif not editor.strip():
            st.error("Enter a name in 'Edited by'.")
        else:
            handle.update_video_metadata(
                picked, location=location or None, camera_source=camera or None, edited_by=editor.strip()
            )
            st.success("Metadata saved. Reports generated afterwards read live from this row.")
            st.rerun()

    st.markdown("**One-click analysis**")
    c1, c2 = st.columns(2)
    with c1:
        reasoning = st.checkbox("Enable reasoning", value=False)
        if st.button("Trigger agent analyze", width="stretch"):
            res = agent.analyze_incident(picked, reasoning=reasoning)
            if res.ok:
                st.success(f"Analysis triggered: {res.data}")
            elif res.not_implemented:
                st.info(res.error)
            else:
                st.warning(res.error)
    with c2:
        if st.button("Draft report via mock LLM", width="stretch"):
            res = agent.draft_report_via_llm(
                prompt=f"Video {video['filename']} at {video.get('location') or 'unknown location'}."
            )
            report = res.data if res.ok else canned_incident_report(video["filename"])
            if not res.ok:
                st.caption(f"(LLM path unavailable: {res.error} - using a canned draft.)")
            if handle is None:
                st.json(report.model_dump())
            else:
                rid = handle.insert_report(video_id=picked, report=report.model_dump())
                handle.set_video_status(picked, "analyzed")
                st.success(f"Draft report #{rid} saved. Review it on the Report Review page.")
