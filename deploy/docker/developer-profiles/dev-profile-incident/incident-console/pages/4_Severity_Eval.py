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

"""Human-vs-AI severity evaluation (product-facing agreement check)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db_reports import DBReports
from ui import bootstrap, get_db_or_notice

bootstrap("Severity Eval", "Rate severity independently and compare against the AI")

handle = get_db_or_notice()
if handle is None:
    st.stop()

reports = DBReports(handle).list_reports()
if not reports:
    st.caption("No reports to rate.")
    st.stop()

by_id = {r["id"]: r for r in reports}
picked = st.selectbox(
    "Report",
    options=list(by_id),
    format_func=lambda i: f"#{i} - {by_id[i].get('incident_type') or 'other'} (AI severity {by_id[i].get('severity')})",
)
report = by_id[picked]
ai_sev = int(report.get("severity") or 1)

with st.form("severity_eval"):
    st.write(f"**AI severity:** {ai_sev}")
    st.caption(report.get("description") or "(no description)")
    human = st.slider("Your severity", 1, 5, value=ai_sev)
    rater = st.text_input("Rater", placeholder="your name (freeform)")
    submit = st.form_submit_button("Submit rating", type="primary")

if submit:
    if not rater.strip():
        st.error("Enter a rater name.")
    else:
        handle.insert_severity_eval(
            incident_id=report["id"],
            model_run_id=report.get("model_run_id"),
            ai_severity=ai_sev,
            human_severity=int(human),
            rater=rater.strip(),
        )
        st.success("Rating recorded.")
        st.rerun()

st.divider()
st.subheader("Agreement")

evals = handle.list_severity_evals()
if not evals:
    st.caption("No ratings logged yet.")
    st.stop()

agree = [e for e in evals if e.get("ai_severity") == e.get("human_severity")]
rate = len(agree) / len(evals)
st.metric("Exact agreement rate", f"{rate:.0%}", help=f"{len(evals)} rating(s)")

df = pd.DataFrame(evals)
df["agree"] = df["ai_severity"] == df["human_severity"]
st.dataframe(
    df[["incident_id", "ai_severity", "human_severity", "rater", "agree"]],
    hide_index=True,
    width="stretch",
)
