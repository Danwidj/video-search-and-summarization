# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030190000_auto_join.sql (automatic join record).

Run by the hermetic harness (test_baseline.py discovers and invokes this file).
Connects to the shared pgserver via the PGSERVER_URI environment variable.
"""

from __future__ import annotations

import json
import os

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


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

REASONS = [{"kind": "same_place", "label": "Same place", "detail": "lift lobby"}]


def new_incident():
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(name, inc):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc))


def record_of(video):
    return one(conn, "SELECT auto_joined_score, auto_joined_reasons, auto_joined_at FROM public.videos WHERE id = %s", (video,))


def auto_merge(target, source, score=0.62, reasons=REASONS):
    return one(conn, "SELECT public.auto_merge_incidents(%s, %s, %s, %s)", (target, source, score, json.dumps(reasons)))[0]


@test("auto-join: videos carry no record until joined automatically")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        new_video("a.mp4", inc)
        assert record_of("a.mp4") == (None, None, None)


@test("auto-join: the merge result is unchanged and the moved videos get the score, reasons and time; the target's own video does not")
def _():
    with conn.transaction(force_rollback=True):
        old, new = new_incident(), new_incident()
        new_video("old.mp4", old)
        new_video("new.mp4", new)
        result = auto_merge(old, new)
        assert result["incident_id"] == old and result["source_incident_id"] == new and result["moved_video_ids"] == ["new.mp4"], result
        score, reasons, at = record_of("new.mp4")
        assert score == 0.62 and reasons == REASONS and at is not None, (score, reasons, at)
        assert record_of("old.mp4") == (None, None, None)
        assert one(conn, "SELECT incident_id FROM public.videos WHERE id = 'new.mp4'")[0] == old
        assert one(conn, "SELECT count(*) FROM public.incidents WHERE id = %s", (new,))[0] == 0


@test("auto-join: a moved video that already has a record keeps it")
def _():
    with conn.transaction(force_rollback=True):
        a, b, c = new_incident(), new_incident(), new_incident()
        new_video("a.mp4", a)
        new_video("b.mp4", b)
        new_video("c.mp4", c)
        auto_merge(b, c, 0.9)
        first = record_of("c.mp4")
        auto_merge(a, b, 0.55)
        assert record_of("c.mp4") == first, (record_of("c.mp4"), first)
        assert record_of("b.mp4")[0] == 0.55


@test("auto-join: a score outside 0 to 1 is refused and merges nothing")
def _():
    for bad in (-0.1, 1.5):
        with conn.transaction(force_rollback=True):
            a, b = new_incident(), new_incident()
            new_video("a.mp4", a)
            new_video("b.mp4", b)
            try:
                auto_merge(a, b, bad)
            except errors.Error as exc:
                assert "between 0 and 1" in str(exc), str(exc)
            else:
                raise AssertionError("no error")
    with conn.transaction(force_rollback=True):
        a = new_incident()
        new_video("a.mp4", a)
        try:
            conn.execute("UPDATE public.videos SET auto_joined_score = 2 WHERE id = 'a.mp4'")
        except errors.CheckViolation:
            pass
        else:
            raise AssertionError("column accepted a score above 1")


@test("auto-join: moving a video out clears its record and records the pair as rejected")
def _():
    with conn.transaction(force_rollback=True):
        old, new = new_incident(), new_incident()
        new_video("old.mp4", old)
        new_video("new.mp4", new)
        auto_merge(old, new)
        assert record_of("new.mp4")[0] is not None
        moved = one(conn, "SELECT public.remove_video('new.mp4', 'move')")[0]
        assert moved["incident_id"] == old and moved["new_incident_id"] != old, moved
        assert record_of("new.mp4") == (None, None, None)
        status = one(conn, "SELECT status FROM public.incident_match_suggestions WHERE LEAST(incident_a_id, incident_b_id) = %s AND GREATEST(incident_a_id, incident_b_id) = %s",
                     (min(old, moved["new_incident_id"]), max(old, moved["new_incident_id"])))[0]
        assert status == "rejected", status


@test("auto-join: deleting a video leaves the others' records alone")
def _():
    with conn.transaction(force_rollback=True):
        old, new = new_incident(), new_incident()
        new_video("old.mp4", old)
        new_video("new.mp4", new)
        new_video("new2.mp4", new)
        auto_merge(old, new)
        one(conn, "SELECT public.remove_video('new2.mp4', 'delete')")
        assert record_of("new.mp4")[0] == 0.62


@test("auto-join: only the service role may run auto_merge_incidents")
def _():
    fn = "public.auto_merge_incidents(bigint, bigint, double precision, jsonb)"
    conn.execute("RESET ROLE")
    try:
        for role in ("anon", "authenticated"):
            assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))[0], role
        assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (fn,))[0]
    finally:
        conn.execute("SET ROLE service_role")


conn.close()
print(f"\n{len(PASSED)} passed (test_auto_join)")
