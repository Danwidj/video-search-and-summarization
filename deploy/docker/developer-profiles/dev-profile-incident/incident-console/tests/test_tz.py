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

"""Display-only UTC -> SGT conversion. Storage is never touched here."""

import datetime as _dt

from tz import DISPLAY_TZ_LABEL, to_display_tz


def test_none_passes_through():
    assert to_display_tz(None) is None


def test_naive_datetime_is_assumed_utc_and_shifted_by_8_hours():
    naive = _dt.datetime(2026, 1, 1, 0, 0, 0)
    converted = to_display_tz(naive)
    assert converted.tzinfo is not None
    assert converted.utcoffset() == _dt.timedelta(hours=8)
    assert (converted.hour, converted.day) == (8, 1)


def test_aware_utc_datetime_is_converted_not_reinterpreted():
    aware = _dt.datetime(2026, 1, 1, 23, 0, 0, tzinfo=_dt.UTC)
    converted = to_display_tz(aware)
    assert (converted.day, converted.hour) == (2, 7)


def test_no_daylight_saving_across_the_year():
    winter = to_display_tz(_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC))
    summer = to_display_tz(_dt.datetime(2026, 7, 1, tzinfo=_dt.UTC))
    assert winter.utcoffset() == summer.utcoffset() == _dt.timedelta(hours=8)


def test_display_tz_label_is_sgt():
    assert DISPLAY_TZ_LABEL == "SGT"
