# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030180000_matching.sql (P3.7).

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

RUN = "run@2026-10-30T09:00:00Z"


def new_incident():
    return one(conn, "INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def vec(*head):
    """A 1024-dim vector literal starting with head, zero elsewhere."""
    values = list(head) + [0.0] * (1024 - len(head))
    return "[" + ",".join(str(v) for v in values) + "]"


def new_video(name, inc, embedding=None):
    """Create a video in an incident, with one analysis carrying the embedding (or none)."""
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc))
    if embedding is not None:
        add_analysis(name, embedding)


def add_analysis(video, embedding):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (RUN,))
    conn.execute("INSERT INTO public.video_analyses (video_id, model_run_id, payload, embedding) "
                 "VALUES (%s, %s, '{}', %s::extensions.vector)", (video, RUN, embedding))


def shortlist(video, *args):
    return conn.execute("SELECT incident_id, similarity, best_video_id FROM public.shortlist_similar_incidents(%s"
                        + ", %s" * len(args) + ")", (video, *args)).fetchall()


def record(a, b, score=0.8, reasons=("same place",)):
    return one(conn, "SELECT public.record_match_suggestion(%s, %s, %s, %s)", (a, b, score, json.dumps(list(reasons))))[0]


def reject(suggestion_id):
    return one(conn, "SELECT public.reject_match_suggestion(%s)", (suggestion_id,))[0]


def row(suggestion_id):
    return one(conn, "SELECT status, decided_at, score FROM public.incident_match_suggestions WHERE id = %s",
               (suggestion_id,))


# --- shortlist_similar_incidents ---------------------------------------------------------

@test("p3.7: shortlist ranks other incidents by similarity and never includes the video's own incident")
def _():
    with conn.transaction(force_rollback=True):
        mine, near, far = new_incident(), new_incident(), new_incident()
        new_video("new.mp4", mine, vec(1, 0))
        new_video("sibling.mp4", mine, vec(1, 0))
        new_video("near.mp4", near, vec(1, 0.1))
        new_video("far.mp4", far, vec(0, 1))
        rows = shortlist("new.mp4", 5, -1.0)
        assert [r[0] for r in rows] == [near, far], rows
        assert rows[0][1] > rows[1][1] and rows[0][2] == "near.mp4"
        assert all(r[0] != mine for r in rows)


@test("p3.7: an incident scores its best video using each video's latest analysis")
def _():
    with conn.transaction(force_rollback=True):
        mine, other = new_incident(), new_incident()
        new_video("new.mp4", mine, vec(1, 0))
        new_video("a.mp4", other, vec(0, 1))
        new_video("b.mp4", other, vec(1, 0.05))
        rows = shortlist("new.mp4")
        assert len(rows) == 1 and rows[0][0] == other and rows[0][2] == "b.mp4" and rows[0][1] > 0.99, rows
        # A newer analysis of a.mp4 replaces its older one.
        add_analysis("a.mp4", vec(1, 0))
        rows = shortlist("new.mp4")
        assert rows[0][1] > 0.999 and rows[0][2] == "a.mp4", rows


@test("p3.7: shortlist skips accepted and rejected pairs but keeps pending ones")
def _():
    with conn.transaction(force_rollback=True):
        mine, rejected, accepted, pending, open_ = (new_incident() for _ in range(5))
        new_video("new.mp4", mine, vec(1, 0))
        for name, inc in (("r.mp4", rejected), ("a.mp4", accepted), ("p.mp4", pending), ("o.mp4", open_)):
            new_video(name, inc, vec(1, 0.1))
        # Stored in the reverse order on purpose: the pair is unordered.
        for inc, status in ((rejected, "rejected"), (accepted, "accepted"), (pending, "pending")):
            conn.execute("INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score, status) "
                         "VALUES (%s, %s, 0.5, %s)", (inc, mine, status))
        assert sorted(r[0] for r in shortlist("new.mp4")) == sorted([pending, open_])


@test("p3.7: shortlist honours the limit and the minimum similarity")
def _():
    with conn.transaction(force_rollback=True):
        mine = new_incident()
        new_video("new.mp4", mine, vec(1, 0))
        incidents = []
        for i, tilt in enumerate((0.0, 0.2, 1.0, 5.0)):
            inc = new_incident()
            incidents.append(inc)
            new_video(f"c{i}.mp4", inc, vec(1, tilt))
        assert [r[0] for r in shortlist("new.mp4", 2, -1.0)] == incidents[:2]
        assert shortlist("new.mp4", 0, -1.0) == []
        assert [r[0] for r in shortlist("new.mp4", 10, 0.95)] == incidents[:2]
        assert shortlist("new.mp4", 10, 1.1) == []


@test("p3.7: shortlist is empty for an unknown video, a video with no analysis or no embedding, and no candidates")
def _():
    with conn.transaction(force_rollback=True):
        mine, other = new_incident(), new_incident()
        new_video("other.mp4", other, vec(1, 0))
        assert shortlist("missing.mp4") == []
        new_video("bare.mp4", mine)
        assert shortlist("bare.mp4") == []
        conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (RUN,))
        conn.execute("INSERT INTO public.video_analyses (video_id, model_run_id, payload) VALUES ('bare.mp4', %s, '{}')", (RUN,))
        assert shortlist("bare.mp4") == []
        # Candidates without an embedding are not listed.
        new_video("embedded.mp4", mine, vec(1, 0))
        third = new_incident()
        new_video("plain.mp4", third)
        assert [r[0] for r in shortlist("embedded.mp4", 5, -1.0)] == [other]


# --- record_match_suggestion -------------------------------------------------------------

@test("p3.7: record_match_suggestion stores a pending suggestion with its score and reasons")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        out = record(a, b, 0.75, ("same place", "same event type"))
        assert out["created"] is True and out["status"] == "pending", out
        status, decided_at, score = row(out["suggestionId"])
        assert (status, decided_at, score) == ("pending", None, 0.75)
        reasons = one(conn, "SELECT reasons FROM public.incident_match_suggestions WHERE id = %s", (out["suggestionId"],))[0]
        assert reasons == ["same place", "same event type"]


@test("p3.7: record_match_suggestion keeps an existing pair as it is, in either order and any status")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        first = record(a, b, 0.6)
        again = record(b, a, 0.9, ("new reason",))
        assert again == {"suggestionId": first["suggestionId"], "status": "pending", "created": False}, again
        assert row(first["suggestionId"])[2] == 0.6
        assert one(conn, "SELECT count(*) FROM public.incident_match_suggestions")[0] == 1
        reject(first["suggestionId"])
        after = record(a, b, 0.99)
        assert after["created"] is False and after["status"] == "rejected", after
        assert one(conn, "SELECT count(*) FROM public.incident_match_suggestions")[0] == 1


@test("p3.7: record_match_suggestion refuses the same incident, a bad score and unknown incidents")
def _():
    a = new_incident()
    refused(conn, "SELECT public.record_match_suggestion(%s, %s, 0.5, '[]')", (a, a), contains="against itself")
    b = new_incident()
    for score in (-0.1, 1.1):
        refused(conn, "SELECT public.record_match_suggestion(%s, %s, %s, '[]')", (a, b, score), contains="between 0 and 1")
    refused(conn, "SELECT public.record_match_suggestion(%s, %s, NULL, '[]')", (a, b), contains="between 0 and 1")
    refused(conn, "SELECT public.record_match_suggestion(%s, NULL, 0.5, '[]')", (a,), contains="required")
    refused(conn, "SELECT public.record_match_suggestion(%s, 987654321, 0.5, '[]')", (a,), kind=errors.ForeignKeyViolation)
    conn.execute("DELETE FROM public.incidents WHERE id IN (%s, %s)", (a, b))


# --- reject_match_suggestion -------------------------------------------------------------

@test("p3.7: reject_match_suggestion marks a pending suggestion rejected and keeps the row")
def _():
    with conn.transaction(force_rollback=True):
        a, b = new_incident(), new_incident()
        sid = record(a, b)["suggestionId"]
        assert reject(sid) == {"suggestionId": sid, "status": "rejected"}
        status, decided_at, _score = row(sid)
        assert status == "rejected" and decided_at is not None


@test("p3.7: rejecting twice keeps the first decision time; an accepted or unknown suggestion is refused")
def _():
    with conn.transaction(force_rollback=True):
        a, b, c = new_incident(), new_incident(), new_incident()
        sid = record(a, b)["suggestionId"]
        reject(sid)
        first = row(sid)[1]
        assert reject(sid)["status"] == "rejected" and row(sid)[1] == first
        accepted = record(a, c)["suggestionId"]
        conn.execute("UPDATE public.incident_match_suggestions SET status = 'accepted' WHERE id = %s", (accepted,))
        refused(conn, "SELECT public.reject_match_suggestion(%s)", (accepted,), contains="already accepted")
        assert row(accepted)[0] == "accepted"
    refused(conn, "SELECT public.reject_match_suggestion(987654321)", contains="does not exist")


@test("p3.7: a rejected pair is never shortlisted again and a recorded pair is not re-created")
def _():
    with conn.transaction(force_rollback=True):
        mine, other = new_incident(), new_incident()
        new_video("new.mp4", mine, vec(1, 0))
        new_video("old.mp4", other, vec(1, 0.1))
        assert [r[0] for r in shortlist("new.mp4")] == [other]
        sid = record(mine, other)["suggestionId"]
        reject(sid)
        assert shortlist("new.mp4") == []
        assert record(other, mine)["created"] is False


@test("p3.7: deleting either incident deletes its suggestions")
def _():
    with conn.transaction(force_rollback=True):
        a, b, c = new_incident(), new_incident(), new_incident()
        record(a, b)
        record(b, c)
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (b,))
        assert one(conn, "SELECT count(*) FROM public.incident_match_suggestions")[0] == 0


@test("p3.7: only the service role may run the matching functions")
def _():
    fns = ("shortlist_similar_incidents(text, integer, double precision)",
           "record_match_suggestion(bigint, bigint, double precision, jsonb)",
           "reject_match_suggestion(bigint)")
    conn.execute("RESET ROLE")
    try:
        for role in ("anon", "authenticated"):
            for fn in fns:
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, f"public.{fn}"))[0], (role, fn)
        for fn in fns:
            assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (f"public.{fn}",))[0], fn
    finally:
        conn.execute("SET ROLE service_role")


conn.close()
print(f"\n{len(PASSED)} passed (test_matching)")
