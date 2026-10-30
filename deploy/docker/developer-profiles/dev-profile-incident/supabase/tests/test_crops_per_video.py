# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030120000_crops_per_video.sql (P3.3).

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


def new_video(name, inc):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", inc))


def new_revision(inc, revision_no, names=()):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING", (RUN,))
    return one(conn, """INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, payload, video_names)
                        VALUES (%s, %s, 'ai', %s, '{"overview":{},"cameras":[]}', %s) RETURNING id""",
               (inc, revision_no, RUN, list(names)))[0]


def crop(item_id, image=None, video_id=None, item_type="entity", **extra):
    out = {"item_type": item_type, "item_id": item_id, "image": image if image is not None else f"evidence/{item_id}.jpg",
           "timestamp_seconds": 5, "bounding_box": [1, 2, 3, 4], **extra}
    if video_id is not None:
        out["video_id"] = video_id
    return out


def rpc(name, *args):
    marks = ", ".join(["%s"] * len(args))
    return one(conn, f"SELECT public.{name}({marks})", tuple(
        json.dumps(a) if isinstance(a, (list, dict)) else a for a in args))[0]


def crops_of(video):
    return sorted(conn.execute("SELECT revision_id, item_type, item_id, image FROM public.evidence_crops "
                               "WHERE video_id = %s ORDER BY 2, 3", (video,)).fetchall())


def setup_two_videos():
    inc = new_incident()
    new_video("front.mp4", inc)
    new_video("back.mp4", inc)
    rev = new_revision(inc, 1, ("front.mp4", "back.mp4"))
    return inc, rev


# --- searchable_revision_id --------------------------------------------------------------

@test("p3.3: searchable_revision_id is NULL for an incident with no revision or an unknown incident")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        assert rpc("searchable_revision_id", inc) is None
        assert rpc("searchable_revision_id", 987654321) is None


@test("p3.3: searchable_revision_id is the newest revision, then the official one")
def _():
    with conn.transaction(force_rollback=True):
        inc = new_incident()
        other = new_incident()
        r1 = new_revision(inc, 1)
        assert rpc("searchable_revision_id", inc) == r1
        r2 = new_revision(inc, 2)
        assert rpc("searchable_revision_id", inc) == r2
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (r1, inc))
        assert rpc("searchable_revision_id", inc) == r1
        r3 = new_revision(inc, 3)
        assert rpc("searchable_revision_id", inc) == r1, r3
        assert rpc("searchable_revision_id", other) is None


# --- replace_video_crops -----------------------------------------------------------------

@test("p3.3: replace_video_crops stores one video's crops with that video as source")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        n = rpc("replace_video_crops", inc, "front.mp4", rev, [crop("E1"), crop("I1", item_type="instrument")])
        assert n == 2, n
        assert crops_of("front.mp4") == [(rev, "entity", "E1", "evidence/E1.jpg"), (rev, "instrument", "I1", "evidence/I1.jpg")]
        assert crops_of("back.mp4") == []


@test("p3.3: replace_video_crops replaces only that video and drops its stale rows on older revisions")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev1 = setup_two_videos()
        rev2 = new_revision(inc, 2, ("front.mp4", "back.mp4"))
        rpc("replace_video_crops", inc, "front.mp4", rev1, [crop("E1")])
        rpc("replace_video_crops", inc, "back.mp4", rev1, [crop("E9")])
        n = rpc("replace_video_crops", inc, "front.mp4", rev2, [crop("E2")])
        assert n == 1
        assert crops_of("front.mp4") == [(rev2, "entity", "E2", "evidence/E2.jpg")]
        assert crops_of("back.mp4") == [(rev1, "entity", "E9", "evidence/E9.jpg")]


@test("p3.3: replace_video_crops with a NULL revision or an empty list only deletes")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        rpc("replace_video_crops", inc, "front.mp4", rev, [crop("E1")])
        assert rpc("replace_video_crops", inc, "front.mp4", rev, []) == 0
        assert crops_of("front.mp4") == []
        rpc("replace_video_crops", inc, "front.mp4", rev, [crop("E1")])
        assert conn.execute("SELECT public.replace_video_crops(%s, 'front.mp4', NULL, %s)", (inc, json.dumps([crop("E1")]))).fetchone()[0] == 0
        assert crops_of("front.mp4") == []


@test("p3.3: replace_video_crops skips items without an image or a valid type and keeps one row per item")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        n = rpc("replace_video_crops", inc, "front.mp4", rev, [
            crop("E1"), crop("E1", image="evidence/dup.jpg"), crop("E2", image="  "), crop("E3", item_type="vehicle"),
            crop("", image="evidence/x.jpg"), "junk"])
        assert n == 1, n
        assert [r[2] for r in crops_of("front.mp4")] == ["E1"]


@test("p3.3: replace_video_crops fills defaults and refuses a video or revision of another incident")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        rpc("replace_video_crops", inc, "front.mp4", rev, [{"item_type": "asset", "item_id": "A1", "image": "evidence/a.jpg"}])
        row = one(conn, "SELECT item_name, description, timestamp_seconds, bounding_box FROM public.evidence_crops WHERE video_id = 'front.mp4'")
        assert row == ("asset", "", 0, [0, 0, 1000, 1000]), row
        other = new_incident()
        new_video("elsewhere.mp4", other)
        other_rev = new_revision(other, 1, ("elsewhere.mp4",))
        refused(conn, "SELECT public.replace_video_crops(%s, 'elsewhere.mp4', %s, '[]')", (inc, rev), contains="is not in incident")
        refused(conn, "SELECT public.replace_video_crops(%s, 'front.mp4', %s, '[]')", (inc, other_rev), contains="is not in incident")
        refused(conn, "SELECT public.replace_video_crops(%s, 'front.mp4', %s, '{}')", (inc, rev), contains="must be a list")


# --- set_revision_crops ------------------------------------------------------------------

@test("p3.3: set_revision_crops sets every video's crops on the searchable revision and replaces older rows")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev1 = setup_two_videos()
        rpc("replace_video_crops", inc, "front.mp4", rev1, [crop("OLD")])
        rev2 = new_revision(inc, 2, ("front.mp4", "back.mp4"))
        out = rpc("set_revision_crops", inc, rev2, [
            crop("E1", video_id="front.mp4"), crop("E2", video_id="back.mp4"), crop("E3", video_id="back.mp4")])
        assert out == {"incidentId": inc, "revisionId": rev2, "crops": 3}, out
        assert crops_of("front.mp4") == [(rev2, "entity", "E1", "evidence/E1.jpg")]
        assert [r[2] for r in crops_of("back.mp4")] == ["E2", "E3"]
        # The same item id on two videos is two rows.
        rpc("set_revision_crops", inc, rev2, [crop("E1", video_id="front.mp4"), crop("E1", video_id="back.mp4")])
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (rev2,))[0] == 2


@test("p3.3: set_revision_crops leaves other incidents alone and an empty list clears the incident")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        other = new_incident()
        new_video("elsewhere.mp4", other)
        other_rev = new_revision(other, 1, ("elsewhere.mp4",))
        rpc("replace_video_crops", other, "elsewhere.mp4", other_rev, [crop("K1")])
        rpc("set_revision_crops", inc, rev, [crop("E1", video_id="front.mp4")])
        assert rpc("set_revision_crops", inc, rev, [])["crops"] == 0
        assert crops_of("front.mp4") == []
        assert len(crops_of("elsewhere.mp4")) == 1


@test("p3.3: set_revision_crops follows the official revision and refuses any other revision")
def _():
    with conn.transaction(force_rollback=True):
        inc, r1 = setup_two_videos()
        r2 = new_revision(inc, 2, ("front.mp4", "back.mp4"))
        refused(conn, "SELECT public.set_revision_crops(%s, %s, '[]')", (inc, r1), contains="not the searchable revision")
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (r1, inc))
        refused(conn, "SELECT public.set_revision_crops(%s, %s, '[]')", (inc, r2), contains="not the searchable revision")
        assert rpc("set_revision_crops", inc, r1, [crop("E1", video_id="front.mp4")])["revisionId"] == r1
        refused(conn, "SELECT public.set_revision_crops(%s, NULL, '[]')", (inc,), contains="not the searchable revision")


@test("p3.3: set_revision_crops refuses an unknown incident, a foreign or missing video_id and a non-list")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        other = new_incident()
        new_video("elsewhere.mp4", other)
        refused(conn, "SELECT public.set_revision_crops(987654321, 1, '[]')", contains="Incident not found")
        refused(conn, "SELECT public.set_revision_crops(%s, %s, %s)", (inc, rev, json.dumps([crop("E1", video_id="elsewhere.mp4")])),
                contains="must name a video_id")
        refused(conn, "SELECT public.set_revision_crops(%s, %s, %s)", (inc, rev, json.dumps([crop("E1")])), contains="must name a video_id")
        refused(conn, "SELECT public.set_revision_crops(%s, %s, '{}')", (inc, rev), contains="must be a list")
        # A refused call changes nothing.
        rpc("replace_video_crops", inc, "front.mp4", rev, [crop("KEEP")])
        refused(conn, "SELECT public.set_revision_crops(%s, %s, %s)", (inc, rev, json.dumps([crop("E1", video_id="nope.mp4")])),
                contains="must name a video_id")
        assert [r[2] for r in crops_of("front.mp4")] == ["KEEP"]


# --- evidence_image and removed functions ------------------------------------------------

@test("p3.3: evidence_image returns the image key of an item, or NULL when it has none")
def _():
    assert rpc("evidence_image", {"image": "evidence/a.jpg"}) == "evidence/a.jpg"
    assert rpc("evidence_image", {"image": "  evidence/b.jpg "}) == "evidence/b.jpg"
    assert rpc("evidence_image", {"image": "  "}) is None
    assert rpc("evidence_image", {"item_id": "E1"}) is None


@test("p3.3: no crop function still takes a video-keyed signature, and apply_r2_rename stays dropped")
def _():
    rows = conn.execute("SELECT p.proname, pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' "
                        "AND p.proname IN ('searchable_revision_id', 'replace_video_crops', 'set_revision_crops', 'apply_r2_rename')").fetchall()
    assert sorted(rows) == [
        ("replace_video_crops", "p_incident_id bigint, p_video_id text, p_revision_id bigint, p_crops jsonb"),
        ("searchable_revision_id", "p_incident_id bigint"),
        ("set_revision_crops", "p_incident_id bigint, p_revision_id bigint, p_crops jsonb"),
    ], rows


@test("p3.3: only the service role may run the crop functions")
def _():
    conn.execute("RESET ROLE")
    try:
        for role in ("anon", "authenticated"):
            for fn in ("searchable_revision_id(bigint)", "evidence_image(jsonb)",
                       "replace_video_crops(bigint, text, bigint, jsonb)", "set_revision_crops(bigint, bigint, jsonb)"):
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, f"public.{fn}"))[0], (role, fn)
        for fn in ("searchable_revision_id(bigint)", "evidence_image(jsonb)",
                   "replace_video_crops(bigint, text, bigint, jsonb)", "set_revision_crops(bigint, bigint, jsonb)"):
            assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (f"public.{fn}",))[0], fn
    finally:
        conn.execute("SET ROLE service_role")


@test("p3.3: deleting a video or its incident removes its crops")
def _():
    with conn.transaction(force_rollback=True):
        inc, rev = setup_two_videos()
        rpc("set_revision_crops", inc, rev, [crop("E1", video_id="front.mp4"), crop("E2", video_id="back.mp4")])
        conn.execute("DELETE FROM public.videos WHERE id = 'front.mp4'")
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 1
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (inc,))
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 0


conn.close()
print(f"\n{len(PASSED)} passed (test_crops_per_video)")
