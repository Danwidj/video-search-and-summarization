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

"""Dashboard: filters + aggregate insights over verified reports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from incident_report import build_insights, dedupe_types
from ui import bootstrap, get_db_or_notice, notifications_panel

bootstrap("Dashboard", "Aggregate insights over verified incident reports")

handle = get_db_or_notice()
notifications_panel(handle)

# Manager-facing analytics only cover verified reports.
# TODO: confirm this boundary against team spec.
reports: list[dict] = handle.list_reports(status="verified") if handle is not None else []

if not reports:
    st.caption("No verified reports yet." if handle is not None else "Connect a database to see the dashboard.")
    st.stop()

df = pd.DataFrame(reports)
all_types = dedupe_types(df.get("incident_type", pd.Series(dtype=str)).dropna().tolist())
all_locations = dedupe_types((df.get("location", pd.Series(dtype=str)).fillna("unknown location")).tolist())

c1, c2, c3 = st.columns(3)
with c1:
    sel_types = st.multiselect("Incident types", all_types, default=all_types)
with c2:
    sel_locs = st.multiselect("Locations", all_locations, default=all_locations)
with c3:
    lo, hi = st.select_slider("Severity range", options=[1, 2, 3, 4, 5], value=(1, 5))

mask = df["incident_type"].isin(sel_types) if "incident_type" in df else pd.Series(True, index=df.index)
if "location" in df:
    mask &= df["location"].fillna("unknown location").isin(sel_locs)
if "severity" in df:
    mask &= df["severity"].fillna(0).astype(int).between(lo, hi)
view = df[mask]

if st.button("Clear filters"):
    st.rerun()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Reports in view", len(view))
m2.metric("Distinct types", int(view["incident_type"].nunique()) if "incident_type" in view else 0)
m3.metric(
    "Severity 4-5",
    int((view["severity"].fillna(0).astype(int) >= 4).sum()) if "severity" in view else 0,
)
m4.metric(
    "Avg confidence",
    f"{view['confidence'].dropna().mean():.0%}"
    if "confidence" in view and not view["confidence"].dropna().empty
    else "n/a",
)

st.subheader("Insights")
for line in build_insights(view.to_dict("records")):
    st.markdown(f"- {line}")

if not view.empty:
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.markdown("##### Count by type")
        st.bar_chart(view["incident_type"].value_counts())
    with col_b:
        st.markdown("##### Count by severity")
        st.bar_chart(view["severity"].fillna(0).astype(int).value_counts().sort_index())

    st.markdown("##### Records")
    cols = [
        c
        for c in ["id", "incident_type", "location", "severity", "confidence", "incident_start", "verified_by"]
        if c in view.columns
    ]
    st.dataframe(view[cols].sort_values("severity", ascending=False), hide_index=True, width="stretch")
else:
    st.info("No records match the current filters.")
