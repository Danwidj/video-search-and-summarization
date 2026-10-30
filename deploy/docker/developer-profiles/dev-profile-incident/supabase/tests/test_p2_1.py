# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030100000_revisions_per_incident.sql (P2.1).

Run by the hermetic harness (test_baseline.py discovers and invokes this file).
Connects to the shared pgserver via the PGSERVER_URI environment variable.
"""

from __future__ import annotations

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


def new_incident(conn):
    return conn.execute("INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()[0]


def new_run(conn, run_id="run@2026-10-30T09:00:00Z"):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (run_id,))
    return run_id


def ai_revision(conn, incident_id, revision_no, names=("a.mp4",), parent_id=None, run_id=None):
    return one(conn, """
        INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, parent_id, payload,
            video_names)
        VALUES (%s, %s, 'ai', %s, %s, '{"overview":{},"cameras":[]}', %s) RETURNING id""",
        (incident_id, revision_no, run_id or new_run(conn), parent_id, list(names)))[0]


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

# --- schema ------------------------------------------------------------------------------

@test("p2.1: report_revisions has incident_id and video_names, no video_id")
def _():
    cols = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'report_revisions'").fetchall()}
    assert cols["incident_id"] == ("bigint", "NO"), cols
    assert cols["video_names"] == ("ARRAY", "NO"), cols
    assert "video_id" not in cols, cols


@test("p2.1: revisions keep the real video names they cover")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        rev = ai_revision(conn, inc, 1, names=("front-door.mp4", "back-yard-camera-left.mp4"))
        names = one(conn, "SELECT video_names FROM public.report_revisions WHERE id = %s", (rev,))[0]
        assert names == ["front-door.mp4", "back-yard-camera-left.mp4"], names


@test("p2.1: revision without incident_id is refused")
def _():
    new_run(conn)
    refused(conn, """INSERT INTO public.report_revisions (revision_no, kind, model_run_id, payload)
                     VALUES (1, 'ai', 'run@2026-10-30T09:00:00Z', '{}')""", kind=errors.NotNullViolation)


@test("p2.1: revision for a missing incident is refused")
def _():
    new_run(conn)
    refused(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, payload)
                     VALUES (-1, 1, 'ai', 'run@2026-10-30T09:00:00Z', '{}')""", kind=errors.ForeignKeyViolation)


# --- numbering and checks ----------------------------------------------------------------

@test("p2.1: (incident, revision number) is unique, and numbers restart per incident")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(conn), new_incident(conn)
        ai_revision(conn, a, 1)
        ai_revision(conn, b, 1)
        ai_revision(conn, a, 2)
    with conn.transaction(force_rollback=True):
        a = new_incident(conn)
        ai_revision(conn, a, 1)
        try:
            ai_revision(conn, a, 1)
        except errors.UniqueViolation:
            return
        raise AssertionError("duplicate (incident, revision_no) accepted")


@test("p2.1: an AI revision needs a model run")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        refused(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, payload)
                         VALUES (%s, 1, 'ai', '{}')""", (inc,), kind=errors.CheckViolation,
                contains="report_revisions_ai_run_check")


@test("p2.1: a human revision needs a creator")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        refused(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, payload)
                         VALUES (%s, 1, 'human', '{}')""", (inc,), kind=errors.CheckViolation,
                contains="report_revisions_human_by_check")
        conn.execute("""INSERT INTO public.report_revisions (incident_id, revision_no, kind, created_by, payload)
                        VALUES (%s, 1, 'human', 'reviewer', '{}')""", (inc,))


# --- parent link -------------------------------------------------------------------------

@test("p2.1: a parent must be a revision of the same incident")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(conn), new_incident(conn)
        parent = ai_revision(conn, a, 1)
        ai_revision(conn, a, 2, parent_id=parent)
        refused(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, created_by, parent_id, payload)
                         VALUES (%s, 1, 'human', 'reviewer', %s, '{}')""", (b, parent),
                kind=errors.ForeignKeyViolation)


# --- official choice ---------------------------------------------------------------------

@test("p2.1: the official revision must belong to the same incident")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(conn), new_incident(conn)
        rev_a, rev_b = ai_revision(conn, a, 1), ai_revision(conn, b, 1)
        refused(conn, "UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (rev_b, a),
                kind=errors.ForeignKeyViolation)
        conn.execute("UPDATE public.incidents SET official_revision_id = %s, official_since = now() WHERE id = %s",
                     (rev_a, a))
        row = one(conn, "SELECT official_revision_id, official_since IS NOT NULL FROM public.incidents WHERE id = %s", (a,))
        assert row == (rev_a, True), row
        conn.execute("UPDATE public.incidents SET official_revision_id = NULL, official_since = NULL WHERE id = %s", (a,))


# --- append-only -------------------------------------------------------------------------

@test("p2.1: revisions stay append-only (no update, no direct delete, coverage immutable)")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        rev = ai_revision(conn, inc, 1)
        refused(conn, "UPDATE public.report_revisions SET video_names = ARRAY['x.mp4'] WHERE id = %s", (rev,),
                contains="append-only")
        refused(conn, "UPDATE public.report_revisions SET note = 'x' WHERE id = %s", (rev,), contains="append-only")
        refused(conn, "DELETE FROM public.report_revisions WHERE id = %s", (rev,), contains="append-only")


@test("p2.1: deleting the incident deletes its revisions (even the official one) and their crops")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        rev = ai_revision(conn, inc, 1)
        ai_revision(conn, inc, 2, parent_id=rev)
        conn.execute("UPDATE public.incidents SET official_revision_id = %s, official_since = now() WHERE id = %s",
                     (rev, inc))
        conn.execute("INSERT INTO public.videos (id, incident_id) VALUES ('crop.mp4', %s)", (inc,))
        conn.execute("""INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                            timestamp_seconds, bounding_box, image)
                        VALUES (%s, 'crop.mp4', 'entity', 'E1', 'Man', 'in red', 1, '{0,0,1,1}', 'crops/e1.jpg')""", (rev,))
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (inc,))
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE incident_id = %s", (inc,))[0] == 0
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (rev,))[0] == 0


@test("p2.1: deleting a video leaves the incident's revisions and their coverage names")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident(conn)
        conn.execute("INSERT INTO public.videos (id, incident_id, source) VALUES ('gone.mp4', %s, 'cam')", (inc,))
        rev = ai_revision(conn, inc, 1, names=("gone.mp4",))
        conn.execute("DELETE FROM public.videos WHERE id = 'gone.mp4'")
        assert one(conn, "SELECT video_names FROM public.report_revisions WHERE id = %s", (rev,))[0] == ["gone.mp4"]


# --- security ----------------------------------------------------------------------------

@test("p2.1: functions that read report_revisions.video_id are gone")
def _():
    left = [r[0] for r in conn.execute(
        "SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
        "AND proname IN ('save_human_revision', 'apply_r2_rename', 'search_report_revisions')").fetchall()]
    assert not left, left


@test("p2.1: report_revisions stays service-role only")
def _():
    conn.execute("RESET ROLE")
    for role in ("anon", "authenticated"):
        assert not one(conn, "SELECT has_table_privilege(%s, 'public.report_revisions', 'SELECT')", (role,))[0], role
    assert one(conn, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.report_revisions'::regclass")[0]
    conn.execute("SET ROLE service_role")


conn.execute("RESET ROLE")
conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
