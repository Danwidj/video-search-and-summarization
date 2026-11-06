# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Calendar periods for "Ask for a chart" (evalv2.references.dashboard_calendar): the rule, the parse, the figures' bounds,
the dated request shape, the development-only records, and the console's own replay on calendar specs (Node, when present)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evalv2.datasets.records import validate_record
from evalv2.references import dashboard as dash
from evalv2.references import dashboard_calendar as cal
from evalv2.references import dashboard_figures as fig
from evalv2.references import dashboard_replay as replay
from evalv2.references import dashboard_snapshot as snap
from evalv2.requests import chart

ALLOWLIST = json.loads((Path(__file__).resolve().parent / "fixtures" / "chart-allowlist.json").read_text())
MAX = ALLOWLIST["calendarPeriods"]["maxRangeDays"]
TODAY = "2026-10-31"
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)  # 1 November in New York and in Singapore: the replay's "today"


def _spec(period, dimension="report_day"):
    return {"metric": "incidents", "dimension": dimension, "period": period, "incidentType": None, "severity": None}


def test_the_allowlist_publishes_the_calendar_limit():
    assert ALLOWLIST["calendarPeriods"] == {"forms": ["month", "day", "from-to"], "maxRangeDays": 366}
    assert MAX == 366


@pytest.mark.parametrize(("period", "today", "days"), [
    ({"month": "2026-10"}, "2026-10-31", ("2026-10-01", "2026-10-31")),
    ({"month": "2026-10"}, "2026-10-06", ("2026-10-01", "2026-10-06")),  # a month still running counts up to today
    ({"month": "2026-12"}, "2027-01-05", ("2026-12-01", "2026-12-31")),
    ({"month": "2028-02"}, "2028-12-31", ("2028-02-01", "2028-02-29")),  # a leap February
    ({"day": "2026-10-31"}, TODAY, ("2026-10-31", "2026-10-31")),  # today itself
    ({"from": "2026-10-01", "to": "2026-10-15"}, TODAY, ("2026-10-01", "2026-10-15")),
    ({"from": "2026-10-15", "to": "2026-10-15"}, TODAY, ("2026-10-15", "2026-10-15")),
    ({"from": "2025-10-31", "to": "2026-10-31"}, TODAY, ("2025-10-31", "2026-10-31")),  # exactly 366 days
    ({"day": "2028-02-29"}, "2028-03-01", ("2028-02-29", "2028-02-29")),
])
def test_a_calendar_period_that_counts_covers_its_days(period, today, days):
    assert cal.calendar_days(period, today, MAX) == days


@pytest.mark.parametrize(("period", "today"), [
    ({"month": "2026-11"}, TODAY),  # a month that starts after today
    ({"month": "2027-01"}, TODAY),
    ({"day": "2026-11-01"}, TODAY),  # a day after today
    ({"from": "2026-10-25", "to": "2026-11-02"}, TODAY),  # a range that runs past today
    ({"from": "2026-11-01", "to": "2026-11-03"}, TODAY),
    ({"from": "2026-10-15", "to": "2026-10-01"}, TODAY),  # reversed
    ({"from": "2025-10-30", "to": "2026-10-31"}, TODAY),  # 367 days
    ({"day": "2026-02-30"}, TODAY),  # not a real day
    ({"day": "2027-02-29"}, "2027-03-01"),  # 2027 is not a leap year
    ({"month": "2026-13"}, TODAY),
    ({"month": "2026-00"}, TODAY),
    ({"month": "2026-1"}, TODAY),  # no leading zero
    ({"day": "2026-10-3"}, TODAY),
    ({"day": "2026-10-28T10:00"}, TODAY),  # a time of day
    ({"month": "2026-10", "day": "2026-10-28"}, TODAY),  # two forms in one object
    ({"from": "2026-10-01"}, TODAY),  # a missing end
    ({"from": "2026-10-01", "to": "2026-10-15", "label": "October"}, TODAY),
    ({}, TODAY),
    ({"day": 20261028}, TODAY),  # not a string
    ("2026-10-28", TODAY),  # a bare string is not a calendar period
    ("october", TODAY),
])
def test_a_calendar_period_that_does_not_count_is_refused(period, today):
    assert cal.calendar_days(period, today, MAX) is None


def test_the_viewers_day_and_midnight_follow_the_time_zone():
    late = datetime(2026, 10, 31, 20, tzinfo=UTC)
    assert cal.today_in("UTC", late) == "2026-10-31"
    assert cal.today_in("Asia/Singapore", late) == "2026-11-01"
    assert cal.start_of_day("2026-10-28", "UTC").isoformat() == "2026-10-28T00:00:00+00:00"
    assert cal.start_of_day("2026-10-28", "Asia/Singapore").astimezone(UTC).isoformat() == "2026-10-27T16:00:00+00:00"
    # New York moves to daylight time on 8 March 2026: midnight is 05:00 UTC before the change, 04:00 UTC after.
    assert cal.start_of_day("2026-03-08", "America/New_York").astimezone(UTC).hour == 5
    assert cal.start_of_day("2026-03-09", "America/New_York").astimezone(UTC).hour == 4


@pytest.mark.parametrize("period", [{"month": "2026-10"}, {"day": "2026-10-28"}, {"from": "2026-10-01", "to": "2026-10-15"}])
def test_the_calendar_forms_parse_and_the_presets_still_do(period):
    assert dash.parse_spec(_spec(period), ALLOWLIST, today=TODAY) == _spec(period)
    assert dash.parse_spec(_spec("last_30_days"), ALLOWLIST, today=TODAY) == _spec("last_30_days")


@pytest.mark.parametrize("period", [{"month": "2026-11"}, {"from": "2026-10-15", "to": "2026-10-01"}, "2026-10-28", "october"])
def test_parse_spec_refuses_what_the_console_refuses(period):
    assert dash.parse_spec(_spec(period), ALLOWLIST, today=TODAY) is None


def test_the_period_is_read_against_the_reference_day_by_default():
    assert dash.parse_spec(_spec({"month": "2026-12"}), ALLOWLIST) is None  # the reference day is 2026-11-06
    assert dash.parse_spec(_spec({"month": "2026-11"}), ALLOWLIST) is not None  # the running month, clipped to that day
    assert dash.parse_spec(_spec({"month": "2026-12"}), ALLOWLIST, today="2026-12-01") is not None


def test_calendar_periods_keep_the_filter_rules():
    spec = {**_spec({"month": "2026-10"}, dimension="model"), "metric": "analyses"}
    assert dash.parse_spec(spec, ALLOWLIST, today=TODAY) == spec
    assert dash.parse_spec({**spec, "incidentType": "assault"}, ALLOWLIST, today=TODAY) is None


def test_the_figures_bounds_are_local_midnights_as_naive_utc_and_half_open():
    query = fig.chart_query(_spec({"from": "2026-10-01", "to": "2026-10-15"}), timezone="Asia/Singapore", now=NOW,
                            allowlist=ALLOWLIST)
    assert query["p_period_start"] == "2026-09-30T16:00:00.000"
    assert query["p_period_end"] == "2026-10-15T16:00:00.000"
    assert query["p_timezone"] == "Asia/Singapore" and query["p_scope"] == "all"
    month = fig.chart_query(_spec({"month": "2026-10"}), timezone="UTC", now=NOW, allowlist=ALLOWLIST)
    assert (month["p_period_start"], month["p_period_end"]) == ("2026-10-01T00:00:00.000", "2026-11-01T00:00:00.000")


def test_the_figures_refuse_a_period_the_reference_day_does_not_count():
    with pytest.raises(ValueError, match="not a calendar period"):
        fig.chart_query(_spec({"month": "2026-12"}), timezone="UTC", now=NOW, allowlist=ALLOWLIST)


def test_a_dated_request_states_today_and_the_zone_and_the_pilot_shapes_do_not():
    dated = chart.build_chart_request("m", "reports per day from 1 to 15 October", "agent-route-v4")
    assert dated["messages"][1]["content"] == (
        f"Today is {cal.REFERENCE_TODAY} (time zone {cal.REFERENCE_TIMEZONE}).\nRequest: reports per day from 1 to 15 October")
    other = chart.build_chart_request("m", "reports per day", "agent-route-v4", {"today": "2026-10-31", "timezone": "UTC"})
    assert other["messages"][1]["content"].startswith("Today is 2026-10-31 (time zone UTC).\nRequest: ")
    for shape in ("console-gateway-v1", "agent-route-v2", "agent-route-v3"):
        assert chart.build_chart_request("m", "reports per day", shape)["messages"][1]["content"] == "reports per day"
    assert chart.GOLDEN_SHAPE == "agent-route-v4"
    assert chart.chart_provenance("agent-route-v4")["date_context"] == chart.REFERENCE_CONTEXT
    assert "date_context" not in chart.chart_provenance("agent-route-v3")


def test_the_development_records_are_marked_and_each_checks_against_the_allowlist():
    records = dash.development_records(ALLOWLIST)
    assert len(records) == len(cal.development_requests())
    assert {record["dataset"] for record in records} == {cal.DATASET}
    periods = {type(record["payload"]["expected"]["period"]) for record in records if "period" in record["payload"]["expected"]}
    assert periods == {dict}
    for record in records:
        assert record["tier"] == "ai_proposed" and record["strata"]["split"] == "development"
        assert validate_record(record) == []
        expected = record["payload"]["expected"]
        if dash.is_refusal(expected):
            assert record["strata"]["class"] == "unsupported"
        else:
            assert dash.parse_spec(expected, ALLOWLIST) == expected
    kinds = {key for record in records for key in ("month", "day", "from") if key in str(record["payload"]["expected"].get("period"))}
    assert kinds == {"month", "day", "from"}
    refused = [record for record in records if dash.is_refusal(record["payload"]["expected"])]
    assert len(refused) >= 3, "a future month, a future day and a reversed range are refused on the reference day"


@pytest.mark.skipif(not replay.available(), reason="needs a Node that strips TypeScript (EVALV2_NODE) and the console")
def test_the_console_draws_calendar_periods_the_same_as_the_recount():
    snapshot = snap.seeded_snapshot(7)
    specs = [
        _spec({"month": "2026-10"}, "incident_type"),
        _spec({"month": "2026-11"}, "report_day"),  # a month still running is clipped to today in both
        _spec({"day": "2026-10-28"}, "severity"),
        _spec({"from": "2026-10-01", "to": "2026-10-15"}, "report_day"),
    ]
    cases = [{"id": f"{i}-{kind}", "spec": spec, "chartType": kind} for i, spec in enumerate(specs) for kind in ("bar", "pie")]
    cases.append({"id": "refused", "spec": None, "chartType": "bar"})
    payload = replay.replay_input(cases, timezone="Asia/Singapore", now=NOW, allowlist=ALLOWLIST,
                                  fetch=lambda p: fig.dashboard(snapshot, p, now=NOW))
    replayed = replay.run_replay(payload)
    assert replayed["missing"] == [] and len(replayed["results"]) == len(cases)
    assert replay.check_against(payload, replayed, allowlist=ALLOWLIST) == {}
