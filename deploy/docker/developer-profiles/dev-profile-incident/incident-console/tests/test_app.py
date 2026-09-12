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

"""Entrypoint registers four pages; all degrade cleanly with no database."""

from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


def test_page_entrypoint_registers_all_pages():
    with patch("streamlit.navigation", wraps=st.navigation) as navigation:
        app = AppTest.from_file("../app.py", default_timeout=10).run()
        assert not app.exception
        assert [page.title for page in navigation.call_args.args[0]] == [
            "Video Catalog",
            "Incident Reports",
            "Analytics Dashboard",
            "Severity Eval",
        ]


@pytest.mark.parametrize(
    "page",
    [
        "../pages/1_Catalog.py",
        "../pages/2_Report_Review.py",
        "../pages/3_Dashboard.py",
        "../pages/4_Severity_Eval.py",
    ],
)
def test_page_shows_db_not_configured_state_without_dsn(page):
    # The autouse no_live_infra fixture scrubs INCIDENT_DB_DSN, so the console
    # has no database here: the page must import, start, and show the visible
    # "database not configured" notice rather than erroring or showing data.
    app = AppTest.from_file(page, default_timeout=15).run()
    assert not app.exception
    assert any("Database not configured" in m.value for m in app.markdown)
    assert not any(b.label == "View and Verify Details" for b in app.button)
