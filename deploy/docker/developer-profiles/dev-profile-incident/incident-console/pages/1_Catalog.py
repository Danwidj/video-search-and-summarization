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

"""Catalog: browse ingested videos and their incident-report counts (browse-only)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import bootstrap, get_db_or_notice

bootstrap("Catalog", "Browse ingested videos and how many incident reports each one has")

handle = get_db_or_notice()
if handle is None:
    st.stop()

STATUS_OPTIONS = ["All", "unanalyzed", "unreviewed", "under review", "verified"]

col_name, col_status = st.columns([3, 1])
with col_name:
    name_q = st.text_input("Filter by filename", placeholder="clip name fragment...").strip()
with col_status:
    status_q = st.selectbox("Status", STATUS_OPTIONS)

rows = handle.list_videos_with_counts(filename_like=name_q or None, status=status_q)

if not rows:
    st.caption("No videos match the current filters.")
else:
    df = pd.DataFrame(rows)
    show_cols = [
        c for c in ["id", "filename", "status", "report_count", "duration", "uploaded_datetime"] if c in df.columns
    ]
    st.dataframe(df[show_cols], hide_index=True, width="stretch")
    st.write(f"{len(rows)} video(s).")
