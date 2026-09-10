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

"""Analytics dashboard over the database-backed incident reports."""

import streamlit as st

from dashboard_view import from_reports, render
from db_reports import DBReports
from theme import apply_base_style, page_header
from ui import get_db_or_notice, notifications_panel

st.set_page_config(page_title="Analytics Dashboard - RISE UP", layout="wide")
apply_base_style()
page_header(
    "Analytics Dashboard",
    "Incident patterns, review priorities, and linked evidence at a glance.",
    "Database incidents and linked evidence · presentation-only analytics scope",
)
handle = get_db_or_notice()
notifications_panel(handle)


def _evidence_rows(db_handle, reports):
    """Flatten DB entities / instruments / assets into dashboard_view's row shape."""
    entities: list[dict] = []
    instruments: list[dict] = []
    assets: list[dict] = []
    for report in reports:
        rid = report["id"]
        for row in db_handle.list_incident_entities(rid):
            entities.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("entity_id"),
                    "Type": row.get("type"),
                    "Description": row.get("description"),
                }
            )
        for row in db_handle.list_incident_instruments(rid):
            instruments.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("instrument_id"),
                    "Entity_ID": row.get("entity_id"),
                    "Name": row.get("name"),
                    "Description": row.get("description"),
                    "Threat_Level": row.get("threat_level"),
                }
            )
        for row in db_handle.list_incident_assets(rid):
            assets.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("asset_id"),
                    "Name": row.get("name"),
                    "Description": row.get("description"),
                }
            )
    return entities, instruments, assets


if handle is None:
    st.stop()
reports = DBReports(handle).list_reports()
entities, instruments, _assets = _evidence_rows(handle, reports)
st.caption(f"Live scope: {len(reports)} incident(s) from the database, with linked entity / instrument evidence.")
render(from_reports(reports), entities, instruments, reports)
