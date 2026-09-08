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
from theme import alert, apply_base_style, page_header
from ui import get_db_or_notice, notifications_panel

st.set_page_config(page_title="Analytics Dashboard - RISE UP", layout="wide")
apply_base_style()
page_header("Analytics Dashboard", "Incident patterns, review priorities, and linked evidence at a glance.", "CSV-backed incident data · Presentation-only analytics scope")
handle = get_db_or_notice()
notifications_panel(handle)
# Preserve the production query and its verified-report scope.
reports = handle.list_reports(status="verified") if handle is not None else []
preview = handle is None and st.toggle("Preview mock / seed data", value=True)
if preview:
    from fixtures.dashboard_seed import load_seed

    seed = load_seed()
    alert("<strong>MOCK / SEED PREVIEW.</strong> Real ground-truth incidents plus clearly flagged synthetic rows. No database writes; locations and workflow statuses are not supplied.", "warning", "🧪")
    render(frame(seed["Incident"]), seed["Entity"], seed["Instrument"])
else:
    st.caption("Live scope: verified reports only. Linked entity/instrument data is not supplied by this query.")
    render(from_reports(reports), [], [], reports)
