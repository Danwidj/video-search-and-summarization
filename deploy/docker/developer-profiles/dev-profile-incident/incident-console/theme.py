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

"""Shared look and feel for the incident console.

Migrated from the rise-up frontend's enterprise-light theme (Inter font, NVIDIA
green accent, pill status/severity badges) so the console keeps a consistent
identity across pages.
"""

from __future__ import annotations

import streamlit as st

_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
        background-color: #F7F8FA !important;
        color: #171A1F !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #E4E7EC !important;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Inter', system-ui, sans-serif !important;
        color: #171A1F !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMainBlockContainer"] div.stButton > button[kind="primary"] {
        background-color: #76B900 !important;
        border: 1px solid #76B900 !important;
        color: #FFFFFF !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMainBlockContainer"] div.stButton > button[kind="primary"]:hover {
        background-color: #5A8F00 !important;
        border-color: #5A8F00 !important;
    }
    input, textarea, [data-baseweb="select"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E4E7EC !important;
        color: #171A1F !important;
        border-radius: 8px !important;
    }
    .badge {
        display: inline-block;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
        border-radius: 20px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .badge-verified { background-color: #F1F8E8; color: #16A34A; border: 1px solid rgba(22,163,74,0.2); }
    .badge-unreviewed { background-color: #F3F4F6; color: #667085; border: 1px solid rgba(102,112,133,0.2); }
    .badge-analyzing { background-color: #FFFBEB; color: #D97706; border: 1px solid rgba(217,119,6,0.2); }
    .badge-failed { background-color: #FEE2E2; color: #DC2626; border: 1px solid rgba(220,38,38,0.2); }
    .sev { display:inline-block; padding:2px 8px; font-size:11px; font-weight:700; border-radius:4px; }
    .sev-5 { background-color:#FEE2E2; color:#DC2626; }
    .sev-4 { background-color:#FFEDD5; color:#EA580C; }
    .sev-3 { background-color:#FEF3C7; color:#D97706; }
    .sev-2 { background-color:#ECFDF5; color:#16A34A; }
    .sev-1 { background-color:#F3F4F6; color:#667085; }
    div[data-testid="stMainBlockContainer"] div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E4E7EC;
        border-radius: 10px;
        padding: 16px 20px;
    }
</style>
"""


def apply_base_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div style="margin: 4px 0 8px 0;">
            <span style="font-size: 26px; font-weight: 700; color: #171A1F; letter-spacing: -0.5px;">{title}</span>
            <span style="font-size: 12px; font-weight: 600; color: #76B900; margin-left: 10px;
                         border: 1px solid #76B900; padding: 2px 8px; border-radius: 4px;">NVIDIA VSS</span>
            {f'<div style="font-size: 14px; color: #667085; margin-top: 4px;">{subtitle}</div>' if subtitle else ""}
        </div>
        <hr style="margin: 12px 0 20px 0; border: 0; border-top: 1px solid #E4E7EC;"/>
        """,
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> str:
    key = (status or "unreviewed").lower()
    cls = {
        "verified": "badge-verified",
        "unreviewed": "badge-unreviewed",
        "unanalyzed": "badge-unreviewed",
        "analyzing": "badge-analyzing",
        "analyzed": "badge-verified",
        "failed": "badge-failed",
    }.get(key, "badge-unreviewed")
    return f'<span class="badge {cls}">{status}</span>'


def severity_badge(severity: int | None) -> str:
    try:
        s = int(severity)
    except (TypeError, ValueError):
        return '<span class="sev sev-1">n/a</span>'
    s = max(1, min(5, s))
    return f'<span class="sev sev-{s}">{s}/5</span>'
