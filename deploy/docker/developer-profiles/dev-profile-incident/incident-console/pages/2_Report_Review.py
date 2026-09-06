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

"""Report review: verify, edit fields, and jump to the incident timestamp."""

from __future__ import annotations

import json

import streamlit as st

import config
from incident_report import (
    INCIDENT_TYPES,
    REPORT_STATUSES,
    playback_start_seconds,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from theme import severity_badge, status_badge
from ui import bootstrap, get_db_or_notice, notifications_panel, video_playback_url

bootstrap("Report Review", "Review, verify, edit, and seek generated incident reports")

handle = get_db_or_notice()
notifications_panel(handle)

f1, f2, f3 = st.columns(3)
with f1:
    type_q = st.selectbox("Type", ["All", *INCIDENT_TYPES])
with f2:
    status_q = st.selectbox("Status", ["All", *REPORT_STATUSES])
with f3:
    kw = st.text_input("Keyword", placeholder="description / location...").strip()

reports: list[dict] = []
if handle is not None:
    reports = handle.list_reports(incident_type=type_q, status=status_q, keyword=kw or None)

if not reports:
    st.caption("No reports to show." if handle is not None else "Connect a database to review reports.")
    st.stop()

by_id = {r["id"]: r for r in reports}
picked = st.selectbox(
    "Report",
    options=list(by_id),
    format_func=lambda i: (
        f"#{i} - {by_id[i].get('incident_type', 'other')} (sev {by_id[i].get('severity')}, {by_id[i].get('status')})"
    ),
)
report = by_id[picked]

st.markdown(
    f"{status_badge(report.get('status', 'unreviewed'))} &nbsp; {severity_badge(report.get('severity'))}",
    unsafe_allow_html=True,
)

col_video, col_edit = st.columns([3, 2], gap="large")

with col_video:
    st.markdown("##### Footage")
    video_row = handle.get_video(report["video_id"]) if report.get("video_id") else {}
    url = video_playback_url(video_row) if video_row else None
    start = playback_start_seconds(report)
    if not report.get("incident_start_confirmed"):
        st.caption("⚠️ Incident start unconfirmed - playback defaults to 0:00.")
    if url:
        try:
            st.video(url, start_time=start)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load video: {exc}")
        st.caption(f"Seek target: {seconds_to_timestamp(start)} (`{url}`)")
    else:
        st.info(
            "No playback URL. Set `INCIDENT_VIDEO_BASE_URL` and ensure the video "
            "row has an `r2_key`. Incident window: "
            f"{report.get('incident_start')} - {report.get('incident_end')}."
        )

with col_edit:
    st.markdown("##### Edit & verify")
    with st.form("edit_report"):
        itype = st.selectbox(
            "Incident type",
            INCIDENT_TYPES,
            index=INCIDENT_TYPES.index(report["incident_type"])
            if report.get("incident_type") in INCIDENT_TYPES
            else len(INCIDENT_TYPES) - 1,
        )
        sev = st.slider("Severity", 1, 5, value=int(report.get("severity") or 1))
        conf = st.slider("Confidence", 0.0, 1.0, value=float(report.get("confidence") or 0.0), step=0.01)
        c1, c2 = st.columns(2)
        with c1:
            start_ts = st.text_input("Start (mm:ss)", value=report.get("incident_start") or "0:00")
        with c2:
            end_ts = st.text_input("End (mm:ss)", value=report.get("incident_end") or "0:00")
        confirmed = st.checkbox("Start confirmed", value=bool(report.get("incident_start_confirmed")))
        location = st.text_input("Location", value=report.get("location") or "")
        desc = st.text_area("Description", value=report.get("description") or "", height=140)
        persons_raw = st.text_area(
            "Persons (JSON list of {description, actions})",
            value=json.dumps(report.get("persons") or [], indent=2),
            height=120,
        )
        editor = st.text_input("Edited by", placeholder="your name (freeform)")
        save = st.form_submit_button("Save changes", type="primary")

    if save:
        if not editor.strip():
            st.error("Enter a name in 'Edited by'.")
        else:
            try:
                persons = json.loads(persons_raw) if persons_raw.strip() else []
            except json.JSONDecodeError as exc:
                persons = None
                st.error(f"Persons JSON invalid: {exc}")
            if persons is not None:
                handle.update_report(
                    picked,
                    fields={
                        "incident_type": itype,
                        "severity": sev,
                        "confidence": conf,
                        "incident_start": seconds_to_timestamp(timestamp_to_seconds(start_ts)),
                        "incident_end": seconds_to_timestamp(timestamp_to_seconds(end_ts)),
                        "incident_start_confirmed": confirmed,
                        "location": location or None,
                        "description": desc,
                        "persons": persons,
                    },
                    edited_by=editor.strip(),
                )
                st.success("Saved.")
                st.rerun()

    st.markdown("---")
    verifier = st.text_input("Verified by", key="verifier", placeholder="your name (freeform)")
    if st.button("Verify report", type="primary", disabled=report.get("status") == "verified"):
        if not verifier.strip():
            st.error("Enter a name in 'Verified by'.")
        else:
            outcome = handle.verify_report(
                picked,
                verified_by=verifier.strip(),
                notify_threshold=config.severity_notify_threshold(),
            )
            st.success("Report verified.")
            if outcome.get("notified"):
                st.toast(
                    f"High-severity alert raised (severity {outcome.get('severity')} "
                    f">= {config.severity_notify_threshold()}).",
                    icon="🔔",
                )
            st.rerun()

    if st.button("Delete report"):
        handle.delete_report(picked)
        st.warning("Deleted.")
        st.rerun()
