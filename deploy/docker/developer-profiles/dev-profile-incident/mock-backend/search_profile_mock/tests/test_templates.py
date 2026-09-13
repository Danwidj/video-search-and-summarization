import datetime as _dt

from search_profile_mock.templates import report_filename


def test_report_filename_unique_within_same_second():
    """Two reports generated in the same wall-clock second must not collide.

    Regression test: report_filename() used to derive the filename purely from
    a one-second-resolution timestamp, so a rapid regenerate (e.g. testing the
    WS and HTTP/SSE report paths back-to-back) produced the same filename
    twice, silently overwriting the first report in state.static_files.
    """
    now = _dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=_dt.UTC)

    first = report_filename(now)
    second = report_filename(now)

    assert first != second


def test_report_filename_shape():
    now = _dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=_dt.UTC)

    name = report_filename(now)

    assert name.startswith("agent_report_20260101_120000_")
    assert name.endswith(".md")
