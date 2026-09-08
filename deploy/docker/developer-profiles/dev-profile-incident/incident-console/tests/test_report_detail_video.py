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

"""Video mapping stays session-local; incident data never requires R2."""

import shutil
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures import dashboard_seed
from fixtures.dashboard_seed import load_seed
from local_reports import LocalReports


def test_csv_edits_persist_and_reload(tmp_path):
    source = dashboard_seed.DATA_DIR
    destination = tmp_path / "data"
    shutil.copytree(source, destination)
    with patch.object(dashboard_seed, "DATA_DIR", destination):
        handle = LocalReports({})
        seed = load_seed()["Incident"]
        first_id = seed[0]["Incident_ID"]
        handle.update_report(first_id, fields={"description": "persisted reviewer correction"})
        assert LocalReports({}).get_report(first_id)["description"] == "persisted reviewer correction"
    assert load_seed()["Incident"][0]["Description"] == seed[0]["Description"]


def test_report_gets_mapped_r2_url_and_seed_timestamp():
    with (
        patch("local_reports.configured", return_value=True),
        patch("local_reports.list_video_keys", return_value=["anomaly/burglary/Burglary001_x264.mp4"]),
        patch("local_reports.playback_url", return_value="https://r2.example/video.mp4"),
    ):
        handle = LocalReports({})
        report = handle.get_report("Burglary001")
        video = handle.get_video("Burglary001")
    assert report["incident_start"] == "00:00:08"
    assert report["incident_end"] == "00:01:57"
    assert video["Filepath"] == "https://r2.example/video.mp4"


def test_two_page_entrypoint():
    with patch("streamlit.navigation", wraps=st.navigation) as navigation:
        app = AppTest.from_file("../app.py", default_timeout=10).run()
        assert not app.exception
        assert [page.title for page in navigation.call_args.args[0]] == ["Incident Reports", "Analytics Dashboard"]
