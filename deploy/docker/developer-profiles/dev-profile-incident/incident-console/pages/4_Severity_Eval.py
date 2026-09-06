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

import config
from incident_report import agreement_rate, severity_disagreement
from ui import bootstrap, get_db_or_notice

bootstrap("Severity Eval", "Rate severity independently and compare against the AI")

handle = get_db_or_notice()

reports: list[dict] = handle.list_reports() if handle is not None else []
if not reports:
    st.caption("No reports to rate." if handle is not None else "Connect a database to run evals.")
    st.stop()

by_id = {r["id"]: r for r in reports}
picked = st.selectbox(
    "Report",
    options=list(by_id),
    format_func=lambda i: f"#{i} - {by_id[i].get('incident_type', 'other')} (AI severity {by_id[i].get('severity')})",
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
        handle.insert_severity_eval(report_id=picked, ai_severity=ai_sev, human_severity=human, rater=rater.strip())
        st.success("Rating recorded.")
        st.rerun()

st.divider()
st.subheader("Agreement")

evals = handle.list_severity_evals()
if not evals:
    st.caption("No ratings logged yet.")
    st.stop()

threshold = config.severity_eval_disagree_threshold()
rate = agreement_rate(evals)
st.metric("Exact agreement rate", f"{rate:.0%}", help=f"{len(evals)} rating(s)")

df = pd.DataFrame(evals)
df["disagreement"] = df.apply(lambda r: severity_disagreement(r["ai_severity"], r["human_severity"], threshold), axis=1)
flagged = df[df["disagreement"]]
st.write(
    f"{len(flagged)} rating(s) differ by more than {threshold} (plan default - `# TODO: confirm against team spec`)."
)
st.dataframe(
    df[["report_id", "ai_severity", "human_severity", "rater", "disagreement"]],
    hide_index=True,
    width="stretch",
)
