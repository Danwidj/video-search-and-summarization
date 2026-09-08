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

import html
import json
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from local_reports import LocalReports
from report_detail import (
    confidence_label,
    normalized,
    render_detail,
    time_label,
)
from theme import TYPE_COLORS, apply_base_style, page_header, severity_badge
from ui import video_playback_url


def render_card_preview(url: str | None, start: int | None) -> None:
    """Render a paused start-frame with a five-second hover preview."""
    if not url:
        st.markdown('<div class="card-preview"><div class="card-preview-poster">🎥</div></div>', unsafe_allow_html=True)
        return
    source = json.dumps(url)
    offset = int(start or 0)
    components.html(
        f"""
        <style>html,body{{margin:0;background:#eef2f5;overflow:hidden}}video{{display:block;width:100%;aspect-ratio:16/9;height:auto;object-fit:cover;border-radius:8px;background:#eef2f5}}</style>
        <video id="preview" muted playsinline preload="metadata"></video>
        <script>
        const v=document.getElementById('preview'), start={offset}, stop=start+5, src={source};
        let hovering=false;
        v.src=src;
        v.addEventListener('loadedmetadata',()=>{{v.currentTime=start;}});
        v.addEventListener('loadeddata',()=>{{if(!hovering){{v.currentTime=start;v.pause();}}}});
        v.addEventListener('seeked',()=>{{if(!hovering)v.pause();}});
        v.addEventListener('mouseenter',()=>{{hovering=true;v.currentTime=start;v.play();}});
        v.addEventListener('mouseleave',()=>{{hovering=false;v.pause();v.currentTime=start;}});
        v.addEventListener('timeupdate',()=>{{if(v.currentTime>=stop){{v.pause();v.currentTime=start;}}}});
        </script>
        """,
        height=185,
        scrolling=False,
    )

st.set_page_config(page_title="Incident Reports - RISE UP", layout="wide")
apply_base_style()
page_header("Incident Reports", "AI-powered post-incident video analysis and reporting platform", "CSV-backed incident data · Changes persist to fixtures/data/incidents.csv · Video playback uses Cloudflare R2")
handle = LocalReports(st.session_state)
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

    video = handle.get_video(selected)
    if not video:
        st.warning("No matching Cloudflare R2 object was found for this incident Filename.", icon="🎥")
    render_detail(handle, report, video)

else:
    st.title("Incident Reports")
    # Restore filters after leaving the detail view (Streamlit cleans hidden widgets).
    saved = st.session_state.get("library_filters", {})
    for key, value in saved.items():
        if key not in st.session_state:
            st.session_state[key] = value
    f1, f2 = st.columns([2, 1])
    kw = f1.text_input("Search incidents", placeholder="Description, type, filename…", key="review_keyword")
    type_q = f2.selectbox(
        "Type",
        ["All", *sorted({r["incident_type"] for r in handle.list_reports() if r["incident_type"]})],
        key="review_type",
    )
    st.session_state["library_filters"] = {key: st.session_state[key] for key in ("review_keyword", "review_type")}
    reports = handle.list_reports(incident_type=type_q, keyword=kw.strip())
    active = []
    if kw.strip():
        active.append(f'query “{kw.strip()}”')
    if type_q != "All":
        active.append(type_q)
    st.markdown(f'<div class="muted"><strong>{len(reports)}</strong> incidents shown · {" · ".join(active) if active else "All available records"}</div>', unsafe_allow_html=True)
    if not reports:
        st.info("No incidents match your filters. Clear the search or choose All.", icon="🔎")
    for offset in range(0, len(reports), 3):
        columns = st.columns(3)
        for column, report in zip(columns, reports[offset : offset + 3], strict=False):
            with column, st.container(border=True):
                fields = normalized(report)
                type_name = (report["incident_type"] or "No classification yet")
                card_class = "untitled" if not report["incident_type"] else ""
                color = TYPE_COLORS.get((report["incident_type"] or "").lower(), TYPE_COLORS[""])
                st.markdown(f'<div class="incident-card {card_class}" style="border-left-color:{color}"><div class="muted">{report["id"]}</div><div class="incident-card-title">{type_name.capitalize()}</div>', unsafe_allow_html=True)
                st.caption(f"Time: {time_label(fields['Start_Timestamp'])} – {time_label(fields['End_Timestamp'])}")
                description = report["description"] or "No description supplied for this incident."
                safe_description = html.escape(description[:145] + ("…" if len(description) > 145 else ""))
                st.markdown(f'<div class="incident-card-description">{safe_description}</div>', unsafe_allow_html=True)
                video = handle.get_video(report["id"])
                video_url = video_playback_url({"r2_key": video.get("Filepath")}) if video and video.get("Filepath") else None
                if video_url:
                    render_card_preview(video_url, fields["Start_Timestamp"])
                else:
                    render_card_preview(None, fields["Start_Timestamp"])
                st.markdown(f'{severity_badge(report["severity"])} <span class="muted">Confidence: {confidence_label(report["confidence"])}</span>', unsafe_allow_html=True)
                filename = html.escape(report["filename"] or "Filename not supplied")
                href = f'?report={quote(str(report["id"]))}'
                st.markdown(f'<a class="source-chip" href="{href}" style="display:inline-block;margin-top:.55rem;color:#5c9200;text-decoration:none">{filename}</a></div>', unsafe_allow_html=True)
                if st.button("View and Verify Details", key=f"open_{report['id']}", width="stretch"):
                    st.query_params["report"] = report["id"]
                    st.rerun()
