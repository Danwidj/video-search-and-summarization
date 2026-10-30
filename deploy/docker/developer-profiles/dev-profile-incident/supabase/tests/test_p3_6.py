# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030170000_ai_revision.sql (P3.6).

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


def vector_literal(index=0):
    values = [0.0] * 1024
    values[index] = 1.0
    return "[" + ",".join(str(v) for v in values) + "]"


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

RUN = "front-door.mp4@2026-10-30T09:00:00Z"
ENVELOPE = json.dumps({"overview": {"title": "Fight", "type": "assault", "severity_level": 4},
                       "cameras": [{"video": "front-door.mp4", "report": {}}]})

CALL = """SELECT public.create_ai_revision(%s, %s, %s, %s::JSONB, '[{"id":"E1"}]'::JSONB, %s, %s, %s, %s, %s, %s::extensions.vector)"""


def new_incident():
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(name, inc_id):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc_id))


def new_run(run_id=RUN):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (run_id,))
    return run_id


def create(inc, names, run=None, kind_type="assault", severity=4, start=None, end=None, embedding=None, note="n"):
    run = run or new_run()
    return one(conn, CALL, (inc, run, note, ENVELOPE, list(names), kind_type, severity, start, end, embedding))[0]


def new_crop(rev, video, item_id, image="evidence/x.jpg"):
    conn.execute("""INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                        timestamp_seconds, bounding_box, image, embedding)
                    VALUES (%s, %s, 'entity', %s, 'n', 'd', 1, '{1,2,3,4}', %s, %s::extensions.vector)""",
                 (rev, video, item_id, image, vector_literal()))


def crops_of(rev):
    return sorted(one(conn, "SELECT array_agg(video_id || ':' || item_id ORDER BY video_id, item_id) FROM public.evidence_crops "
                            "WHERE revision_id = %s", (rev,))[0] or [])


@test("p3.6: a revision stores envelope, evidence, facets, embedding, coverage and note")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("front-door.mp4", inc)
        result = create(inc, ["front-door.mp4"], severity=4, start=2, end=9, embedding=vector_literal(3), note="first")
        assert result["revisionNo"] == 1 and result["crops"] == 0, result
        row = one(conn, """SELECT incident_id, kind, model_run_id, payload, evidence, video_names, incident_type, severity_level,
                                  start_seconds, end_seconds, note, created_by, parent_id, embedding IS NOT NULL
                           FROM public.report_revisions WHERE id = %s""", (result["revisionId"],))
        assert row[:3] == (inc, "ai", RUN), row
        assert row[3]["overview"]["title"] == "Fight" and row[3]["cameras"][0]["video"] == "front-door.mp4", row[3]
        assert row[4] == [{"id": "E1"}] and row[5] == ["front-door.mp4"], row
        assert row[6:] == ("assault", 4, 2, 9, "first", None, None, True), row


@test("p3.6: revision numbers continue per incident")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        new_video("a.mp4", a)
        new_video("b.mp4", b)
        nums = [create(a, ["a.mp4"])["revisionNo"], create(a, ["a.mp4"])["revisionNo"], create(b, ["b.mp4"])["revisionNo"],
                create(a, ["a.mp4"])["revisionNo"]]
        assert nums == [1, 2, 1, 3], nums


@test("p3.6: coverage is the named videos, sorted and without duplicates")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        for name in ("b.mp4", "a.mp4", "c.mp4"):
            new_video(name, inc)
        rev = create(inc, ["b.mp4", "a.mp4", "b.mp4"])["revisionId"]
        assert one(conn, "SELECT video_names FROM public.report_revisions WHERE id = %s", (rev,))[0] == ["a.mp4", "b.mp4"]


@test("p3.6: a video outside the incident is refused and nothing is stored")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        new_video("in.mp4", a)
        new_video("other.mp4", b)
        run = new_run()
        msg = refused(conn, CALL, (a, run, "n", ENVELOPE, ["in.mp4", "other.mp4"], "t", 1, None, None, None), contains="other.mp4")
        assert "in.mp4" not in msg.replace("Not videos of incident", ""), msg
        refused(conn, CALL, (a, run, "n", ENVELOPE, ["ghost.mp4"], "t", 1, None, None, None), contains="ghost.mp4")
        assert one(conn, "SELECT count(*) FROM public.report_revisions")[0] == 0


@test("p3.6: an unknown incident, an empty coverage and a missing run or payload are refused")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        run = new_run()
        refused(conn, CALL, (inc + 1000, run, "n", ENVELOPE, ["a.mp4"], "t", 1, None, None, None), contains="does not exist")
        refused(conn, CALL, (inc, run, "n", ENVELOPE, [], "t", 1, None, None, None), contains="at least one video")
        refused(conn, CALL, (inc, run, "n", ENVELOPE, None, "t", 1, None, None, None), contains="at least one video")
        refused(conn, CALL, (inc, None, "n", ENVELOPE, ["a.mp4"], "t", 1, None, None, None), contains="required")
        refused(conn, CALL, (inc, run, "n", None, ["a.mp4"], "t", 1, None, None, None), contains="required")
        refused(conn, CALL, (inc, "no-such-run", "n", ENVELOPE, ["a.mp4"], "t", 1, None, None, None),
                kind=errors.ForeignKeyViolation)


@test("p3.6: the time range is kept for one video and dropped for several")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        new_video("b.mp4", inc)
        single = create(inc, ["a.mp4"], start=2, end=9)["revisionId"]
        multi = create(inc, ["a.mp4", "b.mp4"], start=2, end=9)["revisionId"]
        q = "SELECT start_seconds, end_seconds FROM public.report_revisions WHERE id = %s"
        assert one(conn, q, (single,)) == (2, 9) and one(conn, q, (multi,)) == (None, None)


@test("p3.6: the covered videos' latest crops are attached, other videos' crops are not")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            new_video(name, inc)
        first = create(inc, ["a.mp4", "b.mp4", "c.mp4"])["revisionId"]
        new_crop(first, "a.mp4", "E1")
        new_crop(first, "b.mp4", "E1")
        new_crop(first, "c.mp4", "E1")
        second = create(inc, ["a.mp4", "b.mp4", "c.mp4"])["revisionId"]
        assert crops_of(second) == ["a.mp4:E1", "b.mp4:E1", "c.mp4:E1"], crops_of(second)
        # a.mp4 gets fresher crops on the second revision; the next revision takes those, not the first's.
        conn.execute("DELETE FROM public.evidence_crops WHERE revision_id = %s AND video_id = 'a.mp4'", (second,))
        new_crop(second, "a.mp4", "E9")
        result = create(inc, ["a.mp4", "b.mp4"])
        assert result["crops"] == 2, result
        assert crops_of(result["revisionId"]) == ["a.mp4:E9", "b.mp4:E1"], crops_of(result["revisionId"])
        # Older revisions keep their own rows; c.mp4 was not covered so nothing of it moved.
        assert crops_of(first) == ["a.mp4:E1", "b.mp4:E1", "c.mp4:E1"]
        image, embedded = one(conn, "SELECT image, embedding IS NOT NULL FROM public.evidence_crops WHERE revision_id = %s "
                                    "AND video_id = 'b.mp4'", (result["revisionId"],))
        assert image == "evidence/x.jpg" and embedded


@test("p3.6: a video with no crops adds none, and a moved video brings its crops")
def _():
    with conn.transaction(force_rollback=True):
        old, new = new_incident(), new_incident()
        new_video("moved.mp4", old)
        new_video("plain.mp4", new)
        rev = create(old, ["moved.mp4"])["revisionId"]
        new_crop(rev, "moved.mp4", "E1")
        conn.execute("UPDATE public.videos SET incident_id = %s WHERE id = 'moved.mp4'", (new,))
        result = create(new, ["moved.mp4", "plain.mp4"])
        assert result["revisionNo"] == 1 and crops_of(result["revisionId"]) == ["moved.mp4:E1"], result
        refused(conn, CALL, (old, new_run(), "n", ENVELOPE, ["moved.mp4"], "t", 1, None, None, None), contains="moved.mp4")


@test("p3.6: the official pointer is untouched and revisions stay append-only")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        rev = create(inc, ["a.mp4"])["revisionId"]
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (rev, inc))
        create(inc, ["a.mp4"])
        assert one(conn, "SELECT official_revision_id FROM public.incidents WHERE id = %s", (inc,))[0] == rev
        refused(conn, "UPDATE public.report_revisions SET video_names = '{}' WHERE id = %s", (rev,))


@test("p3.6: only the service role may call create_ai_revision")
def _():
    conn.execute("RESET ROLE")
    sig = "public.create_ai_revision(BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT[], TEXT, INTEGER, INTEGER, INTEGER, extensions.vector)"
    for role in ("anon", "authenticated", "public"):
        assert not one(conn, "SELECT has_function_privilege(%s, %s::regprocedure, 'EXECUTE')", (role, sig))[0], role
    assert one(conn, "SELECT has_function_privilege('service_role', %s::regprocedure, 'EXECUTE')", (sig,))[0]
    conn.execute("SET ROLE service_role")


conn.execute("RESET ROLE")
conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
