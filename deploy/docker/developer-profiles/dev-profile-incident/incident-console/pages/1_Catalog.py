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

"""Catalog: browse ingested videos, upload new ones, and trigger analysis."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from agent_client import AgentClient
from catalog_actions import current_status, ensure_video_registered, should_keep_polling, upload_and_record
from theme import alert
from ui import bootstrap, get_db_or_notice

bootstrap("Catalog", "Browse ingested videos and how many incident reports each one has")

handle = get_db_or_notice()
if handle is None:
    st.stop()


@st.dialog("Upload video")
def _upload_dialog() -> None:
    uploaded = st.file_uploader("Video file", type=["mp4", "mkv"])
    if st.button("Upload", type="primary", disabled=uploaded is None):
        with st.spinner("Uploading to the agent..."):
            result = upload_and_record(AgentClient(), handle, filename=uploaded.name, content=uploaded.getvalue())
        if result.ok:
            st.success(f"Uploaded. New video id: {result.data}")
            st.rerun()
        elif result.not_implemented:
            alert("Upload isn't available on this backend yet.", "info", "ℹ️")
        else:
            alert(f"Upload failed: {result.error}", "error", "!")


col_name, col_status, col_upload = st.columns([3, 1, 1])
with col_name:
    name_q = st.text_input("Filter by filename", placeholder="clip name fragment...").strip()
with col_status:
    STATUS_OPTIONS = ["All", "unanalyzed", "unreviewed", "under review", "verified"]
    status_q = st.selectbox("Status", STATUS_OPTIONS)
with col_upload:
    st.write("")
    st.write("")
    if st.button("Upload video"):
        _upload_dialog()

rows = handle.list_videos_with_counts(filename_like=name_q or None, status=status_q)

if not rows:
    st.caption("No videos match the current filters.")
else:
    df = pd.DataFrame(rows)
    show_cols = [
        c for c in ["id", "filename", "status", "report_count", "duration", "uploaded_datetime"] if c in df.columns
    ]
    st.dataframe(df[show_cols], hide_index=True, width="stretch")
    st.write(f"{len(rows)} video(s).")

    st.markdown('<div class="section-heading">Analyze a video</div>', unsafe_allow_html=True)
    ids = [r["id"] for r in rows]
    col_pick, col_reason, col_go = st.columns([2, 1, 1])
    with col_pick:
        selected_id = st.selectbox(
            "Video", ids, format_func=lambda i: next(r["filename"] or i for r in rows if r["id"] == i)
        )
    with col_reason:
        reasoning = st.checkbox("Reasoning", help="Ask the agent for a reasoning trace with the analysis")
    with col_go:
        st.write("")
        if st.button("Analyze incident", type="primary"):
            agent = AgentClient()
            # First, ensure the video is registered with VST (self-heal if needed)
            with st.spinner("Checking VST registration..."):
                reg_result = ensure_video_registered(agent, handle, selected_id)
            if not reg_result.ok:
                alert(f"Cannot analyze: {reg_result.error}", "error", "!")
            else:
                # Video is registered (either already was, or self-heal succeeded)
                sensor_id = reg_result.data
                if sensor_id != selected_id:
                    st.info(f"Self-heal complete: registered with VST as `{sensor_id}`")
                with st.spinner("Requesting analysis..."):
                    result = agent.analyze_incident(selected_id, reasoning=reasoning)
                if result.ok:
                    st.session_state["catalog_polling_video_id"] = selected_id
                    st.success("Analysis completed; refreshing the report list.")
                    st.session_state.pop("catalog_polling_video_id", None)
                    st.rerun()
                elif result.not_implemented:
                    alert("Analysis isn't available on this backend yet.", "info", "ℹ️")
                else:
                    alert(f"Analyze failed: {result.error}", "error", "!")

# -- status polling: re-reads the DB on an interval while a video is unanalyzed -- #
polling_id = st.session_state.get("catalog_polling_video_id")
if polling_id:

    @st.fragment(run_every=3)
    def _poll_status(video_id: str) -> None:
        status = current_status(handle, video_id)
        if should_keep_polling(status):
            st.caption(f"⏳ Video `{video_id}` is still unanalyzed - checking again shortly...")
        else:
            st.caption(f"Video `{video_id}` status is now **{status}**.")
            st.session_state.pop("catalog_polling_video_id", None)

    _poll_status(polling_id)
