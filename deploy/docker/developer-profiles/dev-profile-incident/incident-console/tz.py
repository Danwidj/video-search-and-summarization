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

"""Display-only timezone conversion. Storage stays UTC everywhere; only the
values shown to a user in a Streamlit page are converted here."""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Singapore")
DISPLAY_TZ_LABEL = "SGT"


def to_display_tz(value: _dt.datetime | None) -> _dt.datetime | None:
    """Convert a UTC-stored datetime to the display timezone.

    A naive ``datetime`` (as returned by SQLAlchemy for our ``DateTime``
    columns, which are always written via ``_utcnow()`` in ``db.py``) is
    assumed to already be UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.UTC)
    return value.astimezone(DISPLAY_TZ)
