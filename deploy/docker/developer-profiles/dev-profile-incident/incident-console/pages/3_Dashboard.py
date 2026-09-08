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

"""Analytics dashboard with an isolated, optional seed preview."""

import streamlit as st

from dashboard_view import frame, from_reports, render
from theme import apply_base_style
from ui import get_db_or_notice, notifications_panel

st.set_page_config(page_title="Analytics Dashboard - RISE UP", layout="wide")
apply_base_style()
st.markdown(
    '<div style="font-weight:800;font-size:25px;letter-spacing:2px">RISE UP <span style="font-size:10px;letter-spacing:1px;color:#527f00;background:#edf5df;padding:6px 10px;border-radius:20px">NVIDIA POWERED</span></div>',
    unsafe_allow_html=True,
)
st.title("Analytics Dashboard")
st.caption("Incident patterns, review priorities, and linked evidence at a glance.")
handle = get_db_or_notice()
notifications_panel(handle)
# Preserve the production query and its verified-report scope.
reports = handle.list_reports(status="verified") if handle is not None else []
preview = handle is None and st.toggle("Preview mock / seed data", value=True)
if preview:
    from fixtures.dashboard_seed import load_seed

    seed = load_seed()
    st.warning(
        "MOCK / SEED PREVIEW · Real ground-truth incidents plus a clearly-flagged synthetic half. "
        "No database writes. Locations and workflow statuses are not supplied.",
        icon="🧪",
    )
    render(frame(seed["Incident"]), seed["Entity"], seed["Instrument"])
else:
    st.caption("Live scope: verified reports only. Linked entity/instrument data is not supplied by this query.")
    render(from_reports(reports), [], [], reports)
