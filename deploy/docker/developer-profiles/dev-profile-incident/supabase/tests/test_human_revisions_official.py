# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030150000_human_revisions_official.sql (P3.4).

Run by the hermetic harness (test_baseline.py discovers and invokes this file).
Connects to the shared pgserver via the PGSERVER_URI environment variable.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg
from psycopg import errors

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


def refused(conn, sql, params=None, kind=errors.Error, contains=""):
    with conn.transaction(force_rollback=True):
        try:
            conn.execute(sql, params)
        except kind as exc:
            assert contains in str(exc), (contains, str(exc))
            return str(exc)
    raise AssertionError(f"no error from: {sql}")


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

# --- helpers -----------------------------------------------------------------------------

ENV = '{"overview":{"title":"t"},"cameras":[]}'
SAVE = "SELECT public.save_human_revision(%s, %s, %s, %s, %s::jsonb, '[]', 'assault', 3, 1, 9)"
SAVE_CROPS = ("SELECT public.save_human_revision_with_crops(%s, %s, 'dan', 'n', %s::jsonb, '[]', 'assault', 3, 1, 9, %s::jsonb)")
OFFICIAL = "SELECT public.set_official_revision(%s, %s)"


def new_incident():
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(name, inc_id):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc_id))


def new_run(run_id):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (run_id,))


def new_revision(inc_id, names=(), no=1):
    new_run("run@1")
    return one(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, payload, video_names)
                        VALUES (%s, %s, 'ai', 'run@1', %s, %s) RETURNING id""", (inc_id, no, ENV, list(names)))[0]


def crop(video, item_id="E1", **extra):
    return {"video_id": video, "item_type": "entity", "item_id": item_id, "image": f"evidence/{item_id}.jpg", **extra}


def official(inc):
    return one(conn, "SELECT official_revision_id, official_since FROM public.incidents WHERE id = %s", (inc,))


# --- save_human_revision -----------------------------------------------------------------

@test("p3.4: a human revision appends a version that copies the parent's coverage and run")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        parent = new_revision(inc, ["a.mp4", "gone.mp4"])
        out = one(conn, SAVE, (inc, parent, " Dan ", " fixed ", ENV))[0]
        assert out["revisionNo"] == 2 and out["kind"] == "human" and out["parentId"] == parent, out
        assert out["incidentId"] == inc and out["createdBy"] == "Dan" and out["note"] == "fixed", out
        assert out["videoNames"] == ["a.mp4", "gone.mp4"] and out["modelRunId"] == "run@1", out
        row = one(conn, "SELECT video_names, incident_type, severity_level, start_seconds, end_seconds "
                        "FROM public.report_revisions WHERE id = %s", (out["revisionId"],))
        assert row == (["a.mp4", "gone.mp4"], "assault", 3, 1, 9), row
        again = one(conn, SAVE, (inc, out["revisionId"], "Dan", None, ENV))[0]
        assert again["revisionNo"] == 3 and again["note"] is None, again


@test("p3.4: a parent from another incident is refused")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        parent_b = new_revision(b)
        refused(conn, SAVE, (a, parent_b, "Dan", None, ENV), contains="Revision not found for this incident")
        refused(conn, SAVE, (a, None, "Dan", None, ENV), contains="parent revision is required")
        refused(conn, SAVE, (999999, parent_b, "Dan", None, ENV), contains="Incident not found")


@test("p3.4: reviewer name and envelope payload are validated")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        parent = new_revision(inc)
        refused(conn, SAVE, (inc, parent, "  ", None, ENV), contains="reviewer name")
        refused(conn, SAVE, (inc, parent, "x" * 257, None, ENV), contains="reviewer name")
        refused(conn, SAVE, (inc, parent, "Dan", None, '{"incident":{}}'), contains="overview")
        refused(conn, SAVE, (inc, parent, "Dan", None, '{"overview":{},"cameras":{}}'), contains="overview")
        refused(conn, "SELECT public.save_human_revision(%s, %s, 'Dan', NULL, %s::jsonb, '{}', 'a', 1, 1, 2)",
                (inc, parent, ENV), contains="evidence must be a list")


# --- save_human_revision_with_crops ------------------------------------------------------

@test("p3.4: a human revision with crops stores them on the new revision for covered videos")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        new_video("b.mp4", inc)
        parent = new_revision(inc, ["a.mp4", "b.mp4"])
        crops = [crop("a.mp4", "E1", item_name="n", threat_level=2, bounding_box=[1, 2, 3, 4], timestamp_seconds=5),
                 crop("b.mp4", "E1"),
                 {"video_id": "a.mp4", "item_type": "entity", "item_id": "E2"},
                 {"video_id": "a.mp4", "item_type": "bogus", "item_id": "E3", "image": "x"}]
        out = one(conn, SAVE_CROPS, (inc, parent, ENV, json.dumps(crops)))[0]
        assert out["crops"] == 2 and out["videoNames"] == ["a.mp4", "b.mp4"], out
        rows = conn.execute("SELECT video_id, item_id, item_name, threat_level, bounding_box, timestamp_seconds "
                            "FROM public.evidence_crops WHERE revision_id = %s ORDER BY video_id", (out["revisionId"],)).fetchall()
        assert rows == [("a.mp4", "E1", "n", 2, [1, 2, 3, 4], 5), ("b.mp4", "E1", "entity", None, [0, 0, 1000, 1000], 0)], rows
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (parent,))[0] == 0


@test("p3.4: without crops it still saves and reports zero crops")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        parent = new_revision(inc)
        out = one(conn, SAVE_CROPS, (inc, parent, ENV, "[]"))[0]
        assert out["crops"] == 0 and out["revisionNo"] == 2, out
        out = one(conn, "SELECT public.save_human_revision_with_crops(%s, %s, 'dan', NULL, %s::jsonb, '[]', 'a', 1, 1, 2)",
                  (inc, parent, ENV))[0]
        assert out["crops"] == 0, out


@test("p3.4: crops from an uncovered, removed, foreign or unnamed video refuse the whole save")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        new_video("a.mp4", a)
        new_video("other.mp4", b)
        new_video("new.mp4", a)
        parent = new_revision(a, ["a.mp4", "gone.mp4"])
        for bad in (crop("other.mp4"), crop("new.mp4"), crop("gone.mp4"), crop("nope.mp4"),
                    {"item_type": "entity", "item_id": "E1", "image": "x"}):
            refused(conn, SAVE_CROPS, (a, parent, ENV, json.dumps([crop("a.mp4", "E9"), bad])),
                    contains="not a covered video")
        refused(conn, SAVE_CROPS, (a, parent, ENV, '{"x":1}'), contains="crops must be a list")
        refused(conn, SAVE_CROPS, (b, parent, ENV, "[]"), contains="Revision not found for this incident")
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE incident_id = %s", (a,))[0] == 1
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 0


# --- set_official_revision ---------------------------------------------------------------

@test("p3.4: the official revision can be set, kept, moved and cleared")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        first = new_revision(inc)
        second = one(conn, SAVE, (inc, first, "Dan", None, ENV))[0]["revisionId"]
        assert official(inc) == (None, None)
        out = one(conn, OFFICIAL, (inc, first))[0]
        assert out["incidentId"] == inc and out["officialRevisionId"] == first and out["officialSince"], out
        rev, since = official(inc)
        assert rev == first and since is not None
        conn.execute("UPDATE public.incidents SET official_since = official_since - interval '1 day' WHERE id = %s", (inc,))
        old = official(inc)[1]
        one(conn, OFFICIAL, (inc, first))
        assert official(inc)[1] == old, "same revision keeps its time"
        one(conn, OFFICIAL, (inc, second))
        assert official(inc)[0] == second and official(inc)[1] > old
        out = one(conn, OFFICIAL, (inc, None))[0]
        assert out["officialRevisionId"] is None and out["officialSince"] is None, out
        assert official(inc) == (None, None)
        assert one(conn, OFFICIAL, (inc, None))[0]["officialRevisionId"] is None


@test("p3.4: only the incident's own revisions can be official")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        mine = new_revision(a)
        theirs = new_revision(b)
        refused(conn, OFFICIAL, (a, theirs), contains="Revision not found for this incident")
        refused(conn, OFFICIAL, (a, 999999), contains="Revision not found for this incident")
        refused(conn, OFFICIAL, (999999, mine), contains="Incident not found")
        assert official(a) == (None, None)


# --- security ----------------------------------------------------------------------------

@test("p3.4: the three functions are service role only")
def _():
    sigs = ["public.save_human_revision(BIGINT, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER)",
            "public.save_human_revision_with_crops(BIGINT, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB)",
            "public.set_official_revision(BIGINT, BIGINT)"]
    conn.execute("RESET ROLE")
    try:
        for sig in sigs:
            assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,))[0], sig
            for role in ("anon", "authenticated"):
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))[0], (role, sig)
        n = one(conn, "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                      "WHERE n.nspname = 'public' AND p.proname IN ('save_human_revision', 'save_human_revision_with_crops', 'set_official_revision')")[0]
        assert n == 3, n
    finally:
        conn.execute("SET ROLE service_role")


print(f"\n{len(PASSED)} passed")
