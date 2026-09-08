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

"""Detail-view tests use existing canned test content, never UI seed data."""

from streamlit.testing.v1 import AppTest

from fixtures.dashboard_seed import load_seed
from incident_report import canned_incident_report
from report_detail import confidence_label, normalized, seconds


def test_missing_values_and_strict_times():
    assert all(value is None for value in normalized({}).values())
    assert seconds(0) == 0
    assert seconds("1:02:03") == 3723
    assert seconds("1:99") is None
    assert seconds(-1) is None
    assert confidence_label(None) == "Not supplied"
    assert confidence_label(0) == "0.0%"
    assert "invalid" in confidence_label(float("nan"))
    fields = normalized(canned_incident_report().model_dump())
    assert fields["Duration"] == 22
    assert normalized({"Start_Timestamp": 9, "End_Timestamp": 2})["Duration"] is None


def test_detail_navigation_and_inline_edit():
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=10).run()
    assert not app.exception
    assert len([b for b in app.button if b.label == "View and Verify Details"]) == 72
    next(b for b in app.button if b.label == "View and Verify Details").click().run()
    assert not app.exception
    assert app.query_params["report"] == ["Burglary001"]
    app.toggle[0].set_value(True).run()
    next(b for b in app.button if b.label == "Cancel").click().run()
    assert not app.exception
    assert app.toggle[0].value is False
    next(b for b in app.button if b.label == "← Back to Incident Reports").click().run()
    assert not app.exception
    assert "report" not in app.query_params


def test_missing_record():
    app = AppTest.from_file("../pages/2_Report_Review.py")
    app.query_params["report"] = "missing"
    app.run()
    assert not app.exception
    assert any("was not found" in i.value for i in app.info)


def test_inline_edit_cancel_discards_draft():
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=10)
    app.query_params["report"] = "Burglary001"
    app.run()
    original = load_seed()["Incident"][0]["Description"]
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert len(app.text_area) == 1
    # The read-only description is replaced, not repeated beside an edit form.
    assert not any(t.value == original for t in app.text)
    app.text_area[0].set_value("Unsaved reviewer draft")
    next(b for b in app.button if b.label == "Cancel").click().run()
    assert not app.exception
    assert app.toggle[0].value is False
    app.toggle[0].set_value(True).run()
    assert app.text_area[0].value == original
