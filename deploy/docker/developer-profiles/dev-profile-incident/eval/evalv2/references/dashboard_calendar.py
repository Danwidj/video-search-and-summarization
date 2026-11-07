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

"""Calendar periods for "Ask for a chart" (the console's ``domain/chart-period.ts``, re-implemented for evaluation).

A reply may name one calendar month (``{"month": "YYYY-MM"}``), one day (``{"day": "YYYY-MM-DD"}``) or the days from
one date to another (``{"from": ..., "to": ...}``, both included). The console counts it only when it is a real date,
not starting after today in the viewer's time zone, not reversed and at most ``maxRangeDays`` (366) long. A month or range
that ends after today counts up to today (the span is measured on those days). :func:`calendar_days` and :func:`parse_period` are that rule; the figures run from local
midnight in the viewer's time zone (:func:`start_of_day`), as the fixed ranges do.

Every evaluation scores against one pinned day, :data:`REFERENCE_TODAY` in :data:`REFERENCE_TIMEZONE`, so a reference
record does not drift with the calendar. :data:`DEVELOPMENT_REQUESTS` are hand-written development requests, not
reviewed: their records are ``ai_proposed`` and carry ``split = development``, and they are not a held-out set.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

REFERENCE_TODAY = "2026-11-06"
REFERENCE_TIMEZONE = "UTC"
DATASET = "dashboard-calendar-development-v0"

_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")
_CALENDAR_KEYS = (frozenset({"month"}), frozenset({"day"}), frozenset({"from", "to"}))


def is_real_day(text: Any) -> bool:
    """A YYYY-MM-DD that is a real calendar day in years 0001 to 9999 (the console also refuses year 0000)."""
    if not isinstance(text, str) or _DAY.fullmatch(text) is None:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def is_real_month(text: Any) -> bool:
    return isinstance(text, str) and _MONTH.fullmatch(text) is not None and 1 <= int(text[5:]) <= 12 and is_real_day(
        f"{text}-01")


def add_days(day: str, count: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=count)).isoformat()


def _month_last_day(month: str) -> str:
    first = date.fromisoformat(f"{month}-01")
    following = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return (following - timedelta(days=1)).isoformat()


def calendar_days(period: Any, today: str, max_days: int) -> tuple[str, str] | None:
    """The first and last day (inclusive, YYYY-MM-DD) a calendar period covers on ``today``, or ``None`` when refused."""
    if not isinstance(period, dict) or frozenset(period) not in _CALENDAR_KEYS:
        return None
    if not all(isinstance(value, str) for value in period.values()):
        return None
    if "month" in period:
        month = period["month"]
        if not is_real_month(month) or f"{month}-01" > today:
            return None
        return f"{month}-01", min(_month_last_day(month), today)
    if "day" in period:
        day = period["day"]
        return (day, day) if is_real_day(day) and day <= today else None
    first, last = period["from"], period["to"]
    if not (is_real_day(first) and is_real_day(last)) or first > last or first > today:
        return None
    last = min(last, today)
    span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    return None if span > max_days else (first, last)


def today_in(timezone: str, now: datetime) -> str:
    """The calendar day in ``timezone`` at ``now`` (an aware instant), as YYYY-MM-DD."""
    return now.astimezone(ZoneInfo(timezone)).date().isoformat()


def start_of_day(day: str, timezone: str) -> datetime:
    """Local midnight at the start of ``day`` in ``timezone``, an aware instant."""
    return datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=ZoneInfo(timezone))


def development_requests() -> list[dict[str, Any]]:
    """Hand-written development requests with the spec the console should read (``None`` is the refusal).

    They are checked against :data:`REFERENCE_TODAY`: the future month, day and range are refused on that day, and they
    are not a held-out set. Each has a single request and no paraphrases.
    """
    severity = {"incidentType": None, "severity": None}
    return [
        {"request": "number of different category of incident throughout october", "expected": {
            "metric": "incidents", "dimension": "incident_type", "period": {"month": "2026-10"}, **severity}},
        {"request": "severity breakdown on 6 November", "expected": {
            "metric": "incidents", "dimension": "severity", "period": {"day": "2026-11-06"}, **severity}},
        {"request": "reports per day from 1 to 15 October", "expected": {
            "metric": "incidents", "dimension": "report_day", "period": {"from": "2026-10-01", "to": "2026-10-15"},
            **severity}},
        {"request": "reports per week in the last week of October", "expected": {
            "metric": "incidents", "dimension": "report_week", "period": {"from": "2026-10-25", "to": "2026-10-31"},
            **severity}},
        # The most recent December not in the future: December 2025 on 6 November 2026.
        {"request": "incident types in December", "expected": {
            "metric": "incidents", "dimension": "incident_type", "period": {"month": "2025-12"}, **severity}},
        {"request": "incident types in December 2026", "expected": None},
        # A range that ends after the reference day counts up to it: 1 October to 6 November 2026.
        {"request": "reports per day from October to December", "expected": {
            "metric": "incidents", "dimension": "report_day", "period": {"from": "2026-10-01", "to": "2026-12-31"},
            **severity}},
        # A running month counts up to the reference day: 1 to 6 November 2026.
        {"request": "severity breakdown in November", "expected": {
            "metric": "incidents", "dimension": "severity", "period": {"month": "2026-11"}, **severity}},
        {"request": "assault severity on 12 November", "expected": None},
        {"request": "reports per day from 20 to 10 October", "expected": None},
        {"request": "reports per day from 1 September 2025 to 1 October 2026", "expected": None},
        {"request": "incidents next month", "expected": None},
    ]
