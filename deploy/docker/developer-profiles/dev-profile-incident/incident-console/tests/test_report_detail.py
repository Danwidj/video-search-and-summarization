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

"""Detail-view helpers use canned test content, never live data."""

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
