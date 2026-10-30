# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030110000_analyses_suggestions_crops.sql (P2.2).

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


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

# --- helpers -----------------------------------------------------------------------------

def new_incident():
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(name, inc_id):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc_id))


def new_run(run_id):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model')", (run_id,))


def new_analysis(video, run):
    return one(conn, """INSERT INTO public.video_analyses (video_id, model_run_id, payload, incident_type, severity_level)
                        VALUES (%s, %s, '{"incident":{"type":"assault"}}', 'assault', 3) RETURNING id""", (video, run))[0]


def new_revision(inc_id, run, names=()):
    return one(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, payload, video_names)
                        VALUES (%s, 1, 'ai', %s, '{"overview":{},"cameras":[]}', %s) RETURNING id""", (inc_id, run, list(names)))[0]


def new_crop(rev, video, item_id="E1"):
    conn.execute("""INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                        timestamp_seconds, bounding_box, image)
                    VALUES (%s, %s, 'entity', %s, 'n', 'd', 1, '{1,2,3,4}', 'evidence/x.jpg')""", (rev, video, item_id))


def columns(table):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s", (table,)).fetchall()}


# --- video_analyses ----------------------------------------------------------------------

@test("p2.2: video_analyses has the planned columns")
def _():
    cols = columns("video_analyses")
    for name in ("id", "video_id", "model_run_id", "payload", "evidence", "incident_type", "severity_level",
                 "start_seconds", "end_seconds", "embedding", "created_at"):
        assert name in cols, (name, cols)
    assert cols["video_id"] == "text" and cols["model_run_id"] == "text", cols
    assert cols["payload"] == "jsonb" and cols["evidence"] == "jsonb", cols


@test("p2.2: several analyses per video are kept and the latest wins")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("front-door.mp4", inc)
        new_run("front-door.mp4@2026-10-30T09:00:00Z")
        new_run("front-door.mp4@2026-10-30T10:00:00Z")
        first = new_analysis("front-door.mp4", "front-door.mp4@2026-10-30T09:00:00Z")
        second = new_analysis("front-door.mp4", "front-door.mp4@2026-10-30T10:00:00Z")
        assert one(conn, "SELECT count(*) FROM public.video_analyses WHERE video_id = 'front-door.mp4'")[0] == 2
        latest = one(conn, "SELECT id FROM public.video_analyses WHERE video_id = 'front-door.mp4' "
                           "ORDER BY created_at DESC, id DESC LIMIT 1")[0]
        assert latest == second and latest != first, (first, second, latest)


@test("p2.2: video_analyses refuses an unknown video, an unknown run and a missing payload")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        new_run("a.mp4@now")
    refused(conn, "INSERT INTO public.video_analyses (video_id, model_run_id, payload) VALUES ('nope.mp4', 'a.mp4@now', '{}')",
            kind=errors.ForeignKeyViolation)
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        refused(conn, "INSERT INTO public.video_analyses (video_id, model_run_id, payload) VALUES ('a.mp4', 'no-run', '{}')",
                kind=errors.ForeignKeyViolation)
        refused(conn, "INSERT INTO public.video_analyses (video_id, model_run_id) VALUES ('a.mp4', 'no-run')",
                kind=errors.NotNullViolation)


@test("p2.2: deleting a video deletes its analyses and crops but keeps revisions and runs")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("gone.mp4", inc)
        new_video("stay.mp4", inc)
        new_run("gone.mp4@now")
        new_analysis("gone.mp4", "gone.mp4@now")
        new_analysis("stay.mp4", "gone.mp4@now")
        rev = new_revision(inc, "gone.mp4@now", ["gone.mp4", "stay.mp4"])
        new_crop(rev, "gone.mp4")
        new_crop(rev, "stay.mp4", "E2")
        conn.execute("DELETE FROM public.videos WHERE id = 'gone.mp4'")
        assert one(conn, "SELECT count(*) FROM public.video_analyses WHERE video_id = 'gone.mp4'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.video_analyses WHERE video_id = 'stay.mp4'")[0] == 1
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE video_id = 'gone.mp4'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE video_id = 'stay.mp4'")[0] == 1
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE id = %s", (rev,))[0] == 1
        assert one(conn, "SELECT count(*) FROM public.model_runs WHERE id = 'gone.mp4@now'")[0] == 1


@test("p2.2: moving a video to another incident keeps its analyses and crops")
def _():
    with conn.transaction(force_rollback=True):
        old, new = new_incident(), new_incident()
        new_video("move.mp4", old)
        new_run("move.mp4@now")
        new_analysis("move.mp4", "move.mp4@now")
        rev = new_revision(old, "move.mp4@now", ["move.mp4"])
        new_crop(rev, "move.mp4")
        conn.execute("UPDATE public.videos SET incident_id = %s WHERE id = 'move.mp4'", (new,))
        assert one(conn, "SELECT count(*) FROM public.video_analyses WHERE video_id = 'move.mp4'")[0] == 1
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE video_id = 'move.mp4'")[0] == 1


@test("p2.2: deleting an incident deletes its videos, analyses and crops")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("cascade.mp4", inc)
        new_run("cascade.mp4@now")
        new_analysis("cascade.mp4", "cascade.mp4@now")
        rev = new_revision(inc, "cascade.mp4@now", ["cascade.mp4"])
        new_crop(rev, "cascade.mp4")
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (inc,))
        for table in ("video_analyses", "evidence_crops"):
            assert one(conn, f"SELECT count(*) FROM public.{table} WHERE video_id = 'cascade.mp4'")[0] == 0, table


# --- evidence_crops.video_id -------------------------------------------------------------

@test("p2.2: evidence_crops.video_id is NOT NULL and part of the primary key")
def _():
    nullable = one(conn, "SELECT is_nullable FROM information_schema.columns "
                         "WHERE table_schema='public' AND table_name='evidence_crops' AND column_name='video_id'")[0]
    assert nullable == "NO", nullable
    pk = one(conn, """SELECT array_agg(a.attname::TEXT ORDER BY array_position(i.indkey::SMALLINT[], a.attnum))
                      FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
                      WHERE i.indrelid = 'public.evidence_crops'::regclass AND i.indisprimary""")[0]
    assert pk == ["revision_id", "video_id", "item_type", "item_id"], pk


@test("p2.2: the same item id can be cropped from two source videos of one revision")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("cam-a.mp4", inc)
        new_video("cam-b.mp4", inc)
        new_run("cam-a.mp4@now")
        rev = new_revision(inc, "cam-a.mp4@now", ["cam-a.mp4", "cam-b.mp4"])
        new_crop(rev, "cam-a.mp4")
        new_crop(rev, "cam-b.mp4")
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s AND item_id = 'E1'", (rev,))[0] == 2
        refused(conn, """INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                             timestamp_seconds, bounding_box, image)
                         VALUES (%s, 'cam-a.mp4', 'entity', 'E1', 'n', 'd', 1, '{1,2,3,4}', 'x.jpg')""", (rev,),
                kind=errors.UniqueViolation)


@test("p2.2: a crop without a known source video is refused")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("cam-a.mp4", inc)
        new_run("cam-a.mp4@now")
        rev = new_revision(inc, "cam-a.mp4@now", ["cam-a.mp4", "cam-b.mp4"])
        refused(conn, """INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                             timestamp_seconds, bounding_box, image)
                         VALUES (%s, 'ghost.mp4', 'entity', 'E1', 'n', 'd', 1, '{1,2,3,4}', 'x.jpg')""", (rev,),
                kind=errors.ForeignKeyViolation)
        refused(conn, """INSERT INTO public.evidence_crops (revision_id, item_type, item_id, item_name, description,
                             timestamp_seconds, bounding_box, image)
                         VALUES (%s, 'entity', 'E1', 'n', 'd', 1, '{1,2,3,4}', 'x.jpg')""", (rev,),
                kind=errors.NotNullViolation)


# --- incident_match_suggestions ----------------------------------------------------------

@test("p2.2: suggestions default to pending and store score and reasons")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        row = one(conn, """INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score, reasons)
                           VALUES (%s, %s, 0.82, '["same entrance", "same time"]') RETURNING status, decided_at, created_at, reasons""",
                  (a, b))
        assert row[0] == "pending" and row[1] is None and row[2] is not None, row
        assert row[3] == ["same entrance", "same time"], row


@test("p2.2: a suggestion against the same incident is refused")
def _():
    with conn.transaction(force_rollback=True):
        a = new_incident()
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.5)",
                (a, a), kind=errors.CheckViolation)


@test("p2.2: one suggestion per unordered pair, in either order")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.5)", (a, b))
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.6)",
                (a, b), kind=errors.UniqueViolation)
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.6)",
                (b, a), kind=errors.UniqueViolation)


@test("p2.2: a rejected pair stays as a row, so the pair cannot be suggested again")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.5)", (a, b))
        conn.execute("UPDATE public.incident_match_suggestions SET status = 'rejected', decided_at = now() "
                     "WHERE incident_a_id = %s", (a,))
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.9)",
                (b, a), kind=errors.UniqueViolation)


@test("p2.2: status must be pending, accepted or rejected and score must be 0 to 1")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score, status) VALUES (%s, %s, 0.5, 'maybe')",
                (a, b), kind=errors.CheckViolation)
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 1.5)",
                (a, b), kind=errors.CheckViolation)
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, -0.1)",
                (a, b), kind=errors.CheckViolation)


@test("p2.2: deleting either incident deletes its suggestions")
def _():
    with conn.transaction(force_rollback=True):
        a, b, c = new_incident(), new_incident(), new_incident()
        conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.5), (%s, %s, 0.5)",
                     (a, b, c, a))
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (b,))
        ids = (a, b, c)
        count = "SELECT count(*) FROM public.incident_match_suggestions WHERE incident_a_id = ANY(%s) OR incident_b_id = ANY(%s)"
        assert one(conn, count, (list(ids), list(ids)))[0] == 1
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (a,))
        assert one(conn, count, (list(ids), list(ids)))[0] == 0


# --- security ----------------------------------------------------------------------------

@test("p2.2: the new tables and their sequences are for the service role only, with RLS on")
def _():
    conn.execute("RESET ROLE")
    for table in ("video_analyses", "incident_match_suggestions", "evidence_crops"):
        assert one(conn, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{table}",))[0], table
        for role in ("anon", "authenticated"):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not one(conn, "SELECT has_table_privilege(%s, %s, %s)", (role, f"public.{table}", priv))[0], (table, role, priv)
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert one(conn, "SELECT has_table_privilege('service_role', %s, %s)", (f"public.{table}", priv))[0], (table, priv)
    for table in ("video_analyses", "incident_match_suggestions"):
        seq = one(conn, "SELECT pg_get_serial_sequence(%s, 'id')", (f"public.{table}",))[0]
        for role in ("anon", "authenticated"):
            assert not one(conn, "SELECT has_sequence_privilege(%s, %s, 'USAGE')", (role, seq))[0], (seq, role)
        assert one(conn, "SELECT has_sequence_privilege('service_role', %s, 'USAGE')", (seq,))[0], seq
    conn.execute("SET ROLE service_role")


conn.execute("RESET ROLE")
conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
