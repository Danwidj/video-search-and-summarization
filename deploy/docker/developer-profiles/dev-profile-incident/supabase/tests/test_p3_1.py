# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030130000_incident_summaries.sql (P3.1).

Run by the hermetic harness (test_baseline.py discovers and invokes this file).
Connects to the shared pgserver via the PGSERVER_URI environment variable.
"""

from __future__ import annotations

import json
import os

import psycopg

PGSERVER_URI = os.environ["PGSERVER_URI"]
PASSED: list[str] = []


def test(name):
    def wrap(fn):
        fn()
        PASSED.append(name)
        print("ok  ", name)
    return wrap


def one(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()


def new_incident(conn):
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(conn, name, incident_id, uploaded="2026-10-30 09:00:00", key=True):
    conn.execute(
        "INSERT INTO public.videos (id, filepath, source, incident_id, uploaded_datetime) VALUES (%s, %s, 'cam-1', %s, %s)",
        (name, f"uploads/{name}" if key else None, incident_id, uploaded))


def new_run(conn, run_id="run@2026-10-30T09:00:00Z"):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (run_id,))
    return run_id


def envelope(title, cameras=(), confidence=0.8):
    return json.dumps({
        "overview": {"title": title, "type": "theft", "severity_level": 3, "description": f"{title} description",
                     "confidence_score": confidence},
        "cameras": [{"video": name, "report": report} for name, report in cameras],
    })


def revision(conn, incident_id, revision_no, names, title="Report", kind="ai", itype="theft", severity=3,
             cameras=(), created="2026-10-30 10:00:00"):
    created_by = "reviewer" if kind == "human" else None
    run_id = new_run(conn) if kind == "ai" else None
    return one(conn, """
        INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, created_by, payload,
            video_names, incident_type, severity_level, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (incident_id, revision_no, kind, run_id, created_by, envelope(title, cameras), list(names), itype, severity,
         created))[0]


def make_official(conn, incident_id, revision_id):
    conn.execute("UPDATE public.incidents SET official_revision_id = %s, official_since = now() WHERE id = %s",
                 (revision_id, incident_id))


def summaries(conn, **named):
    args = ", ".join(f"{k} => %s" for k in named) if named else ""
    return conn.execute(f"SELECT public.list_incident_report_summaries({args})", tuple(named.values())).fetchone()[0]


def by_incident(result):
    return {row["incidentId"]: row for row in result["reports"]}


def dashboard(conn, **named):
    args = ", ".join(f"{k} => %s" for k in named) if named else ""
    return conn.execute(f"SELECT public.get_incident_dashboard({args})", tuple(named.values())).fetchone()[0]


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")


def populate(conn):
    """Incidents of 0, 1 and 3 videos. Returns their ids."""
    empty, single, triple = new_incident(conn), new_incident(conn), new_incident(conn)
    new_video(conn, "single.mp4", single)
    new_video(conn, "angle-b.mp4", triple, uploaded="2026-10-30 09:05:00")
    new_video(conn, "angle-a.mp4", triple, uploaded="2026-10-30 09:01:00")
    new_video(conn, "angle-c.mp4", triple, uploaded="2026-10-30 09:09:00", key=False)
    return empty, single, triple


# --- list ------------------------------------------------------------------------------------

@test("p3.1: one row per incident with video counts for 0, 1 and 3 videos")
def _():
    with conn.transaction(force_rollback=True):
        empty, single, triple = populate(conn)
        revision(conn, single, 1, ["single.mp4"])
        revision(conn, triple, 1, ["angle-a.mp4", "angle-b.mp4"])
        revision(conn, triple, 2, ["angle-a.mp4", "angle-b.mp4", "angle-c.mp4"])
        result = summaries(conn, p_page_size=50)
        rows = by_incident(result)
        assert result["totalItems"] == 3 and len(result["reports"]) == 3, result
        assert rows[empty]["videoCount"] == 0 and rows[single]["videoCount"] == 1 and rows[triple]["videoCount"] == 3
        assert rows[triple]["versionCount"] == 2 and rows[single]["versionCount"] == 1 and rows[empty]["versionCount"] == 0


@test("p3.1: an incident without a revision still lists, with no revision id and no first video")
def _():
    with conn.transaction(force_rollback=True):
        empty, _single, _triple = populate(conn)
        row = by_incident(summaries(conn, p_page_size=50))[empty]
        assert row["revisionId"] is None and row["revisionNo"] is None, row
        assert row["firstVideoName"] is None and row["thumbnail"] is None, row
        assert row["coverage"] == [] and row["missingVideos"] == [] and row["removedVideos"] == [], row
        assert row["title"] == "Incident report" and row["incident_type"] == "Unclassified", row


@test("p3.1: first video is the earliest uploaded; thumbnail key comes from its key")
def _():
    with conn.transaction(force_rollback=True):
        _empty, single, triple = populate(conn)
        revision(conn, single, 1, ["single.mp4"])
        revision(conn, triple, 1, ["angle-a.mp4"])
        rows = by_incident(summaries(conn, p_page_size=50))
        assert rows[triple]["firstVideoName"] == "angle-a.mp4", rows[triple]
        assert rows[triple]["firstVideoKey"] == "uploads/angle-a.mp4", rows[triple]
        assert rows[triple]["thumbnail"] == "thumbnails/uploads/angle-a.mp4.webp", rows[triple]
        assert rows[single]["firstVideoName"] == "single.mp4" and rows[single]["sensorId"] == "cam-1", rows[single]
        assert rows[triple]["uploadedAt"].startswith("2026-10-30T09:01:00"), rows[triple]["uploadedAt"]


@test("p3.1: a first video without a key has no thumbnail key")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        new_video(conn, "no-key.mp4", inc, key=False)
        row = by_incident(summaries(conn, p_page_size=50))[inc]
        assert row["firstVideoName"] == "no-key.mp4" and row["thumbnail"] is None and row["firstVideoKey"] is None, row


@test("p3.1: the card is the official revision, else the latest")
def _():
    with conn.transaction(force_rollback=True):
        _empty, single, triple = populate(conn)
        first = revision(conn, triple, 1, ["angle-a.mp4"], title="First", severity=2)
        latest = revision(conn, triple, 2, ["angle-a.mp4", "angle-b.mp4"], title="Latest", severity=4)
        revision(conn, single, 1, ["single.mp4"], title="Only")
        rows = by_incident(summaries(conn, p_page_size=50))
        assert rows[triple]["revisionId"] == latest and rows[triple]["title"] == "Latest", rows[triple]
        assert rows[triple]["isOfficial"] is False and rows[triple]["officialSince"] is None, rows[triple]
        make_official(conn, triple, first)
        rows = by_incident(summaries(conn, p_page_size=50))
        assert rows[triple]["revisionId"] == first and rows[triple]["title"] == "First", rows[triple]
        assert rows[triple]["isOfficial"] is True and rows[triple]["officialSince"] is not None, rows[triple]
        assert rows[triple]["severity"] == 2 and rows[triple]["versionCount"] == 2, rows[triple]
        assert rows[single]["isOfficial"] is False and rows[single]["title"] == "Only", rows[single]


@test("p3.1: coverage comes from the shown revision, with missing and removed videos worked out")
def _():
    with conn.transaction(force_rollback=True):
        _empty, _single, triple = populate(conn)
        revision(conn, triple, 1, ["angle-a.mp4", "gone.mp4"])
        row = by_incident(summaries(conn, p_page_size=50))[triple]
        assert row["coverage"] == ["angle-a.mp4", "gone.mp4"], row
        assert row["missingVideos"] == ["angle-b.mp4", "angle-c.mp4"], row
        assert row["removedVideos"] == ["gone.mp4"], row
        revision(conn, triple, 2, ["angle-a.mp4", "angle-b.mp4", "angle-c.mp4"])
        row = by_incident(summaries(conn, p_page_size=50))[triple]
        assert row["missingVideos"] == [] and row["removedVideos"] == [], row


@test("p3.1: filters work on the facets of the shown revision, and facets span every camera")
def _():
    with conn.transaction(force_rollback=True):
        _empty, single, triple = populate(conn)
        revision(conn, single, 1, ["single.mp4"], title="Quiet", itype="trespassing", severity=1)
        cameras = [
            ("angle-a.mp4", {"entities": [{"type": "person", "description": "man in red coat"}],
                             "instruments": [{"name": "Crowbar", "description": "pry bar"}], "assets": []}),
            ("angle-b.mp4", {"entities": [{"type": "vehicle", "description": "white van"}], "instruments": [],
                             "assets": [{"name": "Safe", "description": "wall safe"}]}),
        ]
        revision(conn, triple, 1, ["angle-a.mp4", "angle-b.mp4"], title="Break in", itype="theft", severity=4, cameras=cameras)
        assert list(by_incident(summaries(conn, p_type="theft"))) == [triple]
        assert list(by_incident(summaries(conn, p_severity="high"))) == [triple]
        assert list(by_incident(summaries(conn, p_severity="low"))) == [single]
        assert list(by_incident(summaries(conn, p_entities=["white van"]))) == [triple]
        assert list(by_incident(summaries(conn, p_entities=["red coat"]))) == [triple]
        assert list(by_incident(summaries(conn, p_assets=["safe"]))) == [triple]
        assert list(by_incident(summaries(conn, p_instruments=["crowbar"]))) == [triple]
        assert list(by_incident(summaries(conn, p_search="break in"))) == [triple]
        assert list(by_incident(summaries(conn, p_search="angle-c"))) == [triple]
        assert summaries(conn, p_search="nothing-matches")["totalItems"] == 0
        assert summaries(conn, p_page_size=50)["incidentTypes"] == ["theft", "trespassing"]


@test("p3.1: kind and scope filters, paging and sort order")
def _():
    with conn.transaction(force_rollback=True):
        _empty, single, triple = populate(conn)
        revision(conn, single, 1, ["single.mp4"], kind="human", severity=5, created="2026-10-30 08:00:00")
        official = revision(conn, triple, 1, ["angle-a.mp4"], severity=2, created="2026-10-30 12:00:00")
        assert list(by_incident(summaries(conn, p_kind="human"))) == [single]
        assert list(by_incident(summaries(conn, p_scope="official"))) == []
        make_official(conn, triple, official)
        assert list(by_incident(summaries(conn, p_scope="official"))) == [triple]
        newest = [row["incidentId"] for row in summaries(conn, p_page_size=50, p_sort="newest")["reports"]]
        assert newest[0] == triple and newest.index(triple) < newest.index(single), newest
        oldest = [row["incidentId"] for row in summaries(conn, p_page_size=50, p_sort="oldest")["reports"]]
        assert oldest.index(single) < oldest.index(triple), oldest
        high = [row["incidentId"] for row in summaries(conn, p_page_size=50, p_sort="severity-high")["reports"]]
        assert high.index(single) < high.index(triple), high
        paged = summaries(conn, p_page=2, p_page_size=1, p_sort="newest")
        assert len(paged["reports"]) == 1 and paged["totalItems"] == 3, paged


# --- dashboard ---------------------------------------------------------------------------

@test("p3.1: dashboard counts incidents and videos, and ignores non-official revisions in statistics")
def _():
    with conn.transaction(force_rollback=True):
        before = dashboard(conn)
        empty, single, triple = populate(conn)
        revision(conn, single, 1, ["single.mp4"], severity=2, itype="trespassing")
        official = revision(conn, triple, 1, ["angle-a.mp4"], severity=4, itype="theft")
        revision(conn, triple, 2, ["angle-a.mp4", "angle-b.mp4", "angle-c.mp4"], severity=1, itype="loitering")
        make_official(conn, triple, official)
        after = dashboard(conn)
        assert after["videos"]["uploaded"] - before["videos"]["uploaded"] == 4, after["videos"]
        delta = {k: after["incidents"][k] - before["incidents"][k] for k in after["incidents"]}
        assert delta == {"total": 3, "withOfficial": 1, "awaitingSelection": 1, "withoutReport": 1}, delta
        assert after["total"] - before["total"] == 1, after["total"]
        types = {t["type"]: t for t in after["types"]}
        assert types["theft"]["severity"]["high"] >= 1 and "loitering" not in types, types
        assert after["revisions"]["ai"] - before["revisions"]["ai"] == 1, after["revisions"]


@test("p3.1: dashboard facets span every camera of the official revision, counted once per incident")
def _():
    with conn.transaction(force_rollback=True):
        _empty, _single, triple = populate(conn)
        report = {"entities": [{"type": "person", "description": "x"}], "instruments": [], "assets": []}
        official = revision(conn, triple, 1, ["angle-a.mp4", "angle-b.mp4"], cameras=[("angle-a.mp4", report), ("angle-b.mp4", report)])
        make_official(conn, triple, official)
        entity_types = {row["label"]: row["count"] for row in dashboard(conn)["entityTypes"]}
        assert entity_types == {"human": 1}, entity_types


@test("p3.1: dashboard period and filter arguments still apply")
def _():
    with conn.transaction(force_rollback=True):
        _empty, single, triple = populate(conn)
        a = revision(conn, single, 1, ["single.mp4"], severity=2, created="2026-09-01 10:00:00")
        b = revision(conn, triple, 1, ["angle-a.mp4"], severity=4, created="2026-10-15 10:00:00")
        make_official(conn, single, a)
        make_official(conn, triple, b)
        window = dashboard(conn, p_period_start="2026-10-01", p_period_end="2026-11-01")
        assert window["total"] == 1 and window["previous"]["total"] == 1, window
        assert dashboard(conn, p_severity="low")["total"] == 1
        assert dashboard(conn, p_type="theft")["total"] == 2


@test("p3.1: anon and authenticated cannot run the functions")
def _():
    conn.execute("RESET ROLE")
    for role in ("anon", "authenticated"):
        for fn in (
            "public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP, TIMESTAMP, TIME, TIME, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT)",
            "public.get_incident_dashboard(TIMESTAMP, TIMESTAMP, TEXT, TEXT, INTEGER, INTEGER, TEXT)",
        ):
            assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))[0], (role, fn)
    conn.execute("SET ROLE service_role")


conn.close()
print(f"\n{len(PASSED)} passed")
