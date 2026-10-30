# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030160000_merge_remove.sql (P3.5): merge_incidents and remove_video.

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


def new_incident():
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(name, inc):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc))


def new_run(run_id):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (run_id,))


def new_analysis(video, run):
    new_run(run)
    conn.execute("INSERT INTO public.video_analyses (video_id, model_run_id, payload) VALUES (%s, %s, '{}')", (video, run))


def new_revision(inc, no, names):
    new_run("run@now")
    return one(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, payload, video_names)
                        VALUES (%s, %s, 'ai', 'run@now', '{"overview":{},"cameras":[]}', %s) RETURNING id""",
               (inc, no, list(names)))[0]


def new_crop(rev, video, item_id, image):
    conn.execute("""INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                        timestamp_seconds, bounding_box, image)
                    VALUES (%s, %s, 'entity', %s, 'n', 'd', 1, '{1,2,3,4}', %s)""", (rev, video, item_id, image))


def merge(target, source):
    return one(conn, "SELECT public.merge_incidents(%s, %s)", (target, source))[0]


def remove(video, mode):
    return one(conn, "SELECT public.remove_video(%s, %s)", (video, mode))[0]


def count(sql, params=None):
    return one(conn, sql, params)[0]


# --- merge_incidents ---------------------------------------------------------------------

@test("p3.5: merge moves the source's videos and analyses to the target and deletes the source")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        new_video("a1.mp4", a)
        new_video("b1.mp4", b)
        new_video("b2.mp4", b)
        new_analysis("b1.mp4", "b1.mp4@now")
        out = merge(a, b)
        assert out["incident_id"] == a and out["source_incident_id"] == b, out
        assert out["moved_video_ids"] == ["b1.mp4", "b2.mp4"], out
        assert count("SELECT count(*) FROM public.incidents WHERE id = %s", (b,)) == 0
        rows = conn.execute("SELECT id, incident_id FROM public.videos ORDER BY id").fetchall()
        assert rows == [("a1.mp4", a), ("b1.mp4", a), ("b2.mp4", a)], rows
        assert count("SELECT count(*) FROM public.video_analyses WHERE video_id = 'b1.mp4'") == 1


@test("p3.5: merge deletes the source's revisions, crops and suggestions and reports the crop images")
def _():
    with conn.transaction(force_rollback=True):
        a, b, c = new_incident(), new_incident(), new_incident()
        new_video("a1.mp4", a)
        new_video("b1.mp4", b)
        rev_a = new_revision(a, 1, ["a1.mp4"])
        rev_b = new_revision(b, 1, ["b1.mp4"])
        new_crop(rev_a, "a1.mp4", "E1", "evidence/a1.jpg")
        new_crop(rev_b, "b1.mp4", "E1", "evidence/b1.jpg")
        conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.5), (%s, %s, 0.5)",
                     (b, c, a, c))
        out = merge(a, b)
        assert out["orphaned_crop_images"] == ["evidence/b1.jpg"], out
        assert count("SELECT count(*) FROM public.report_revisions WHERE incident_id = %s", (b,)) == 0
        assert count("SELECT count(*) FROM public.report_revisions WHERE id = %s", (rev_a,)) == 1
        assert count("SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (rev_b,)) == 0
        assert count("SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (rev_a,)) == 1
        assert count("SELECT count(*) FROM public.incident_match_suggestions WHERE %s IN (incident_a_id, incident_b_id)", (b,)) == 0
        assert count("SELECT count(*) FROM public.incident_match_suggestions WHERE %s IN (incident_a_id, incident_b_id)", (a,)) == 1


@test("p3.5: merge keeps the target's official choice and drops the source's")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        new_video("a1.mp4", a)
        new_video("b1.mp4", b)
        rev_a = new_revision(a, 1, ["a1.mp4"])
        rev_b = new_revision(b, 1, ["b1.mp4"])
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (rev_a, a))
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (rev_b, b))
        merge(a, b)
        assert count("SELECT official_revision_id FROM public.incidents WHERE id = %s", (a,)) == rev_a


@test("p3.5: merge works with a pending suggestion for the pair, in either order")
def _():
    for flip in (False, True):
        with conn.transaction(force_rollback=True):
            a, b = new_incident(), new_incident()
            new_video("a1.mp4", a)
            new_video("b1.mp4", b)
            pair = (b, a) if flip else (a, b)
            conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.9)", pair)
            assert merge(a, b)["incident_id"] == a
            assert count("SELECT count(*) FROM public.incident_match_suggestions") == 0


@test("p3.5: merge refuses itself, null and unknown incidents")
def _():
    a = None
    with conn.transaction(force_rollback=True):
        a = new_incident()
        refused(conn, "SELECT public.merge_incidents(%s, %s)", (a, a), kind=errors.InvalidParameterValue, contains="into itself")
        refused(conn, "SELECT public.merge_incidents(%s, NULL)", (a,), kind=errors.InvalidParameterValue)
        refused(conn, "SELECT public.merge_incidents(%s, %s)", (a, a + 1000), contains="does not exist")
        refused(conn, "SELECT public.merge_incidents(%s, %s)", (a + 1000, a), contains="does not exist")


# --- remove_video: delete ----------------------------------------------------------------

@test("p3.5: deleting one of several videos removes its analyses and crops, keeps revisions as history")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("gone.mp4", inc)
        new_video("stay.mp4", inc)
        new_analysis("gone.mp4", "gone.mp4@now")
        new_analysis("stay.mp4", "stay.mp4@now")
        rev = new_revision(inc, 1, ["gone.mp4", "stay.mp4"])
        new_crop(rev, "gone.mp4", "E1", "evidence/gone.jpg")
        new_crop(rev, "stay.mp4", "E2", "evidence/stay.jpg")
        out = remove("gone.mp4", "delete")
        assert out == {"mode": "delete", "video_id": "gone.mp4", "incident_id": inc, "new_incident_id": None,
                       "incident_deleted": False, "deleted_video_key": "uploads/gone.mp4",
                       "deleted_crop_images": ["evidence/gone.jpg"]}, out
        assert count("SELECT count(*) FROM public.videos WHERE id = 'gone.mp4'") == 0
        assert count("SELECT count(*) FROM public.video_analyses WHERE video_id = 'gone.mp4'") == 0
        assert count("SELECT count(*) FROM public.evidence_crops WHERE video_id = 'gone.mp4'") == 0
        assert count("SELECT count(*) FROM public.video_analyses WHERE video_id = 'stay.mp4'") == 1
        assert count("SELECT count(*) FROM public.evidence_crops WHERE video_id = 'stay.mp4'") == 1
        assert one(conn, "SELECT video_names FROM public.report_revisions WHERE id = %s", (rev,))[0] == ["gone.mp4", "stay.mp4"]
        assert count("SELECT count(*) FROM public.incidents WHERE id = %s", (inc,)) == 1


@test("p3.5: deleting the last video deletes the incident, revisions, crops and suggestions")
def _():
    with conn.transaction(force_rollback=True):
        inc, other = new_incident(), new_incident()
        new_video("only.mp4", inc)
        new_analysis("only.mp4", "only.mp4@now")
        rev = new_revision(inc, 1, ["only.mp4"])
        new_crop(rev, "only.mp4", "E1", "evidence/only.jpg")
        conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.5)", (inc, other))
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (rev, inc))
        out = remove("only.mp4", "delete")
        assert out["incident_deleted"] is True and out["incident_id"] == inc, out
        assert out["deleted_video_key"] == "uploads/only.mp4" and out["deleted_crop_images"] == ["evidence/only.jpg"], out
        assert count("SELECT count(*) FROM public.incidents WHERE id = %s", (inc,)) == 0
        assert count("SELECT count(*) FROM public.report_revisions WHERE incident_id = %s", (inc,)) == 0
        assert count("SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (rev,)) == 0
        assert count("SELECT count(*) FROM public.video_analyses WHERE video_id = 'only.mp4'") == 0
        assert count("SELECT count(*) FROM public.incident_match_suggestions") == 0


# --- remove_video: move ------------------------------------------------------------------

@test("p3.5: moving a video makes a new incident that holds it with its analyses and crops")
def _():
    with conn.transaction(force_rollback=True):
        old = new_incident()
        new_video("keep.mp4", old)
        new_video("move.mp4", old)
        new_analysis("move.mp4", "move.mp4@now")
        rev = new_revision(old, 1, ["keep.mp4", "move.mp4"])
        new_crop(rev, "move.mp4", "E1", "evidence/move.jpg")
        out = remove("move.mp4", "move")
        new = out["new_incident_id"]
        assert new is not None and new != old, out
        assert out["incident_id"] == old and out["incident_deleted"] is False, out
        assert out["deleted_video_key"] is None and out["deleted_crop_images"] == [], out
        assert count("SELECT incident_id FROM public.videos WHERE id = 'move.mp4'") == new
        assert count("SELECT incident_id FROM public.videos WHERE id = 'keep.mp4'") == old
        assert count("SELECT count(*) FROM public.video_analyses WHERE video_id = 'move.mp4'") == 1
        assert count("SELECT count(*) FROM public.evidence_crops WHERE video_id = 'move.mp4'") == 1
        assert count("SELECT count(*) FROM public.report_revisions WHERE incident_id = %s", (new,)) == 0
        assert one(conn, "SELECT video_names FROM public.report_revisions WHERE id = %s", (rev,))[0] == ["keep.mp4", "move.mp4"]


@test("p3.5: a move records the old and new incident as a rejected pair that cannot be suggested again")
def _():
    with conn.transaction(force_rollback=True):
        old = new_incident()
        new_video("keep.mp4", old)
        new_video("move.mp4", old)
        new = remove("move.mp4", "move")["new_incident_id"]
        row = one(conn, "SELECT status, decided_at, score FROM public.incident_match_suggestions "
                        "WHERE LEAST(incident_a_id, incident_b_id) = %s AND GREATEST(incident_a_id, incident_b_id) = %s",
                  (min(old, new), max(old, new)))
        assert row[0] == "rejected" and row[1] is not None and row[2] == 0, row
        refused(conn, "INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score) VALUES (%s, %s, 0.9)",
                (new, old), kind=errors.UniqueViolation)


@test("p3.5: moving the last video is refused and changes nothing")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("only.mp4", inc)
        before = count("SELECT count(*) FROM public.incidents")
        refused(conn, "SELECT public.remove_video('only.mp4', 'move')", kind=errors.CheckViolation, contains="last video")
        assert count("SELECT count(*) FROM public.incidents") == before
        assert count("SELECT incident_id FROM public.videos WHERE id = 'only.mp4'") == inc


@test("p3.5: remove_video refuses an unknown video, a bad mode and null")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        refused(conn, "SELECT public.remove_video('nope.mp4', 'delete')", contains="does not exist")
        refused(conn, "SELECT public.remove_video('a.mp4', 'archive')", kind=errors.InvalidParameterValue)
        refused(conn, "SELECT public.remove_video('a.mp4', NULL)", kind=errors.InvalidParameterValue)
        assert count("SELECT count(*) FROM public.videos WHERE id = 'a.mp4'") == 1


# --- security ----------------------------------------------------------------------------

@test("p3.5: both functions are executable by the service role only")
def _():
    conn.execute("RESET ROLE")
    for sig in ("public.merge_incidents(bigint, bigint)", "public.remove_video(text, text)"):
        for role in ("anon", "authenticated"):
            assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))[0], (role, sig)
        assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,))[0], sig
    conn.execute("SET ROLE service_role")


conn.execute("RESET ROLE")
conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
