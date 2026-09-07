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

"""Incident library and detail view over the existing dashboard seed data."""

import streamlit as st

from local_reports import LocalReports
from r2_videos import demo_video
from report_detail import (
    SEVERITY_COLORS,
    STATUS_LABELS,
    confidence_label,
    normalized,
    pill,
    render_detail,
    severity_label,
    time_label,
)
from theme import apply_base_style

st.set_page_config(page_title="Incident Reports - RISE UP", layout="wide")
apply_base_style()
st.markdown(
    '<div style="font-size:26px;font-weight:800;letter-spacing:1px">RISE UP <span style="font-size:11px;color:#598d00;background:#eff7e4;padding:5px 10px;border-radius:20px">NVIDIA POWERED</span></div>',
    unsafe_allow_html=True,
)
st.caption("AI-Powered Post-Incident Video Analysis and Intelligent Reporting Platform")
handle = LocalReports(st.session_state)
st.caption(
    "Sample data · Same 18 incidents as the dashboard · Edits and review statuses are session-only. Only video playback uses external storage."
)
if notice := st.session_state.pop("detail_notice", None):
    st.success(notice)
if close_id := st.session_state.pop("detail_close_edit", None):
    st.session_state[f"detail_edit_{close_id}"] = False
selected = st.query_params.get("report")
if selected is not None:
    if st.button("← Back to Incident Reports"):
        del st.query_params["report"]
        st.rerun()
    st.title("Incident Report Details")
    report = handle.get_report(selected)
    if not report:
        st.info("This incident report was not found. Return to the library to select an incident.", icon="📄")
        st.stop()

    def source_video():
        video = handle.get_video(selected)
        if not video:
            video = demo_video(report)
        with st.expander("Link source video from Cloudflare R2", expanded=not bool(video)):
            st.caption(
                "Optional override: paste a public or presigned video URL. Only the video uses external storage; this override lasts for the session."
            )
            with st.form(f"link_video_{selected}"):
                url = st.text_input("Video playback URL", value=handle.get_video(selected).get("Filepath", ""))
                link = st.form_submit_button("Use this video")
            if link:
                try:
                    handle.link_video(selected, url.strip())
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
        return video

    render_detail(handle, report, source_video)

else:
    st.title("Incident Reports")
    # Restore filters after leaving the detail view (Streamlit cleans hidden widgets).
    saved = st.session_state.get("library_filters", {})
    for key, value in saved.items():
        if key not in st.session_state:
            st.session_state[key] = value
    f1, f2, f3 = st.columns([2, 1, 1])
    kw = f1.text_input("Search incidents", placeholder="Description, type, filename…", key="review_keyword")
    type_q = f2.selectbox(
        "Type", ["All", *sorted({r["incident_type"] for r in handle.list_reports()})], key="review_type"
    )
    status_q = f3.selectbox(
        "Status",
        ["All", *STATUS_LABELS],
        key="review_status",
        format_func=lambda s: STATUS_LABELS.get(s, "All Statuses"),
    )
    st.session_state["library_filters"] = {
        key: st.session_state[key] for key in ("review_keyword", "review_type", "review_status")
    }
    reports = handle.list_reports(incident_type=type_q, status=status_q, keyword=kw.strip())
    st.caption(f"{len(reports)} incidents")
    if not reports:
        st.info("No incidents match your filters. Clear the search or choose All.", icon="🔎")
    for offset in range(0, len(reports), 3):
        columns = st.columns(3)
        for column, report in zip(columns, reports[offset : offset + 3], strict=False):
            with column, st.container(border=True):
                fields = normalized(report)
                pill(
                    STATUS_LABELS[report["status"]].upper(),
                    {"verified": "#16854a", "under review": "#ac7800"}.get(report["status"], "#667085"),
                )
                st.caption(f"Incident {report['id']}")
                st.subheader(report["incident_type"].capitalize())
                st.caption(f"Time: {time_label(fields['Start_Timestamp'])} – {time_label(fields['End_Timestamp'])}")
                description = report["description"] or "Description not supplied"
                st.text(description[:135] + ("…" if len(description) > 135 else ""))
                pill(severity_label(report["severity"]), SEVERITY_COLORS.get(report["severity"], "#667085"))
                st.caption(f"Confidence: {confidence_label(report['confidence'])}")
                if st.button("View and Verify Details", key=f"open_{report['id']}", width="stretch"):
                    st.query_params["report"] = report["id"]
                    st.rerun()
