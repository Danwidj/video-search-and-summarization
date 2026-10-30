# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030140000_incident_search.sql (P3.2).

Run by the hermetic harness (test_baseline.py discovers and invokes this file).
Connects to the shared pgserver via the PGSERVER_URI environment variable.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg

PGSERVER_URI = os.environ["PGSERVER_URI"]
PASSED: list[str] = []


def test(name):
    def wrap(fn):
        fn()
        PASSED.append(name)
        print("ok  ", name)
    return wrap


def vec(index):
    values = [0.0] * 1024
    values[index] = 1.0
    return json.dumps(values)


def one(sql, params=None):
    return conn.execute(sql, params).fetchone()


def new_incident():
    return one("INSERT INTO public.incidents DEFAULT VALUES RETURNING id")[0]


def new_video(name, incident_id):
    conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
                 (name, f"uploads/{name}", incident_id))


def new_revision(incident_id, no, names, kind="ai", title="Title", itype="assault", severity=3, embedding=None,
                 start=2, end=9):
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'model') ON CONFLICT DO NOTHING",
                 (f"run-{incident_id}-{no}",))
    payload = json.dumps({"overview": {"title": title, "description": f"{title} description"}, "cameras": []})
    return one("""INSERT INTO public.report_revisions (incident_id, revision_no, kind, model_run_id, created_by, payload,
                      video_names, incident_type, severity_level, start_seconds, end_seconds, embedding)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector) RETURNING id""",
               (incident_id, no, kind, f"run-{incident_id}-{no}" if kind == "ai" else None,
                "reviewer" if kind == "human" else None, payload, names, itype, severity, start, end, embedding))[0]


def crop(revision_id, video_id, item_id, index, ts=5, item_type="entity"):
    conn.execute("""INSERT INTO public.evidence_crops (revision_id, video_id, item_type, item_id, item_name, description,
                        timestamp_seconds, bounding_box, image, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, ARRAY[0, 0, 500, 500], %s, %s::extensions.vector)""",
                 (revision_id, video_id, item_type, item_id, f"{item_id} name", f"{item_id} desc", ts,
                  f"crops/{video_id}/{item_id}.jpg", vec(index)))


def evidence(embedding, **kw):
    args = {"p_query_embedding": embedding, "p_min_similarity": 0.5, **kw}
    sql = "SELECT * FROM public.search_evidence_items(" + ", ".join(f"{k} => %s" for k in args) + ")"
    cur = conn.execute(sql.replace("p_query_embedding => %s", "p_query_embedding => %s::extensions.vector"),
                       list(args.values()))
    names = [d.name for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def revisions(embedding, **kw):
    args = {"p_query_embedding": embedding, **kw}
    sql = ("SELECT * FROM public.search_report_revisions(p_query_embedding => %s::extensions.vector"
           + "".join(f", {k} => %s" for k in kw) + ")")
    cur = conn.execute(sql, [embedding, *kw.values()])
    names = [d.name for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

# --- fixtures: three incidents, one with two videos --------------------------------------------
# A: front-door.mp4 + back-yard.mp4, revision 1 (stale, crops on it) and revision 2 (newest, searchable)
# B: bus-stop.mp4, human revision 1 official, revision 2 newer ai (not searchable while 1 is official)
# C: lobby.mp4, one revision with severity 1 and a different type
conn.execute("BEGIN")
A, B, C = new_incident(), new_incident(), new_incident()
for name, inc in (("front-door.mp4", A), ("back-yard.mp4", A), ("bus-stop.mp4", B), ("lobby.mp4", C)):
    new_video(name, inc)
A1 = new_revision(A, 1, ["front-door.mp4"], title="Old A", embedding=vec(9))
A2 = new_revision(A, 2, ["front-door.mp4", "back-yard.mp4"], title="Break-in", itype="burglary", severity=4,
                  embedding=vec(10))
B1 = new_revision(B, 1, ["bus-stop.mp4"], kind="human", title="Fight", itype="assault", severity=5,
                  embedding=vec(11))
B2 = new_revision(B, 2, ["bus-stop.mp4"], title="Newer B", itype="assault", severity=2, embedding=vec(10))
C1 = new_revision(C, 1, ["lobby.mp4"], title="Lobby", itype="fire", severity=1, embedding=vec(12))
conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (B1, B))

crop(A1, "front-door.mp4", "stale", 0)                      # stale revision: never returned
crop(A2, "front-door.mp4", "crowbar", 0, ts=4, item_type="instrument")
crop(A2, "back-yard.mp4", "intruder", 1, ts=7)
crop(B1, "bus-stop.mp4", "jacket", 0, ts=3)                 # official revision
crop(B2, "bus-stop.mp4", "newer", 0, ts=3)                  # not searchable while B1 is official
crop(C1, "lobby.mp4", "smoke", 2, ts=6, item_type="asset")
conn.execute("COMMIT")

# --- search_evidence_items ---------------------------------------------------------------------

@test("p3.2: evidence hits name the incident and the source video")
def _():
    hits = evidence(vec(1))
    assert [(h["incident_id"], h["video_id"], h["item_id"]) for h in hits] == [(A, "back-yard.mp4", "intruder")], hits
    assert hits[0]["video_filepath"] == "uploads/back-yard.mp4", hits
    assert hits[0]["revision_id"] == A2 and hits[0]["incident_title"] == "Break-in", hits
    assert hits[0]["similarity_score"] > 0.99, hits


@test("p3.2: two videos of one incident are both searchable and name their own video")
def _():
    hits = evidence(vec(0), p_top_k=10)
    got = {(h["incident_id"], h["video_id"], h["item_id"]) for h in hits}
    assert got == {(A, "front-door.mp4", "crowbar"), (B, "bus-stop.mp4", "jacket")}, got


@test("p3.2: only the searchable revision's crops are returned (official, else newest)")
def _():
    ids = {h["item_id"] for h in evidence(vec(0), p_top_k=10)}
    assert "stale" not in ids and "newer" not in ids, ids
    assert {"crowbar", "jacket"} <= ids, ids


@test("p3.2: type filter applies")
def _():
    hits = evidence(vec(0), p_incident_types=["burglary"])
    assert {h["incident_id"] for h in hits} == {A}, hits
    assert evidence(vec(0), p_incident_types=["fire"]) == []


@test("p3.2: severity filters apply to the searchable revision")
def _():
    assert {h["incident_id"] for h in evidence(vec(0), p_min_severity=5)} == {B}
    assert {h["incident_id"] for h in evidence(vec(0), p_max_severity=4)} == {A}
    assert {h["incident_id"] for h in evidence(vec(0), p_min_severity=4, p_max_severity=4)} == {A}
    assert evidence(vec(0), p_min_severity=6) == []


@test("p3.2: item type filter applies")
def _():
    hits = evidence(vec(0), p_item_types=["instrument"])
    assert [h["item_id"] for h in hits] == ["crowbar"], hits


@test("p3.2: scoping to one source video or one incident happens before ranking")
def _():
    hits = evidence(vec(0), p_video_id="front-door.mp4", p_top_k=1)
    assert [(h["video_id"], h["item_id"]) for h in hits] == [("front-door.mp4", "crowbar")], hits
    hits = evidence(vec(0), p_incident_id=B, p_top_k=1)
    assert [h["item_id"] for h in hits] == ["jacket"], hits
    assert evidence(vec(0), p_video_id="lobby.mp4", p_incident_id=A) == []


@test("p3.2: a NULL query lists the scoped crops in time order with similarity 0")
def _():
    hits = evidence(None, p_incident_id=A, p_min_similarity=0.2)
    assert [(h["item_id"], h["similarity_score"]) for h in hits] == [("crowbar", 0.0), ("intruder", 0.0)], hits


@test("p3.2: the minimum similarity drops weak matches")
def _():
    assert evidence(vec(100)) == []


@test("p3.2: an incident with no revision is not returned and nothing breaks")
def _():
    empty = new_incident()
    new_video("empty.mp4", empty)
    assert all(h["incident_id"] != empty for h in evidence(vec(0), p_top_k=50))


# --- search_report_revisions -------------------------------------------------------------------

@test("p3.2: report search returns one hit per incident naming the incident and its videos")
def _():
    hits = revisions(vec(10), p_min_similarity=0.5)
    by_incident = {h["incident_id"]: h for h in hits}
    assert set(by_incident) == {A}, by_incident
    assert by_incident[A]["revision_id"] == A2
    assert by_incident[A]["video_names"] == ["front-door.mp4", "back-yard.mp4"]
    assert by_incident[A]["title"] == "Break-in" and by_incident[A]["description"] == "Break-in description"


@test("p3.2: report search uses the official revision, not a newer one, and never a stale one")
def _():
    hits = revisions(vec(11), p_min_similarity=0.5)
    assert [(h["incident_id"], h["revision_id"]) for h in hits] == [(B, B1)], hits
    assert revisions(vec(9), p_min_similarity=0.5) == []          # A1 is stale
    assert A2 not in [h["revision_id"] for h in revisions(vec(9), p_min_similarity=-1.0) if h["incident_id"] != A]


@test("p3.2: report search carries type, severity and the time range")
def _():
    (hit,) = revisions(vec(12), p_min_similarity=0.5)
    assert (hit["incident_id"], hit["incident_type"], hit["severity_level"], hit["start_seconds"],
            hit["end_seconds"]) == (C, "fire", 1, 2, 9), hit


@test("p3.2: report search respects top_k and ranks by similarity")
def _():
    hits = revisions(vec(10), p_top_k=2, p_min_similarity=-1.0)
    assert len(hits) == 2 and hits[0]["incident_id"] == A, hits


@test("p3.2: search functions are callable by service_role only")
def _():
    for sig in ("public.search_evidence_items(extensions.vector, integer, double precision, text[], text[], integer, "
                "integer, text, bigint)",
                "public.search_report_revisions(extensions.vector, integer, double precision)"):
        assert one("SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,))[0]
        for role in ("anon", "authenticated"):
            assert not one("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))[0], (role, sig)


@test("p3.2: only one overload of each search function exists")
def _():
    for name in ("search_evidence_items", "search_report_revisions"):
        count = one("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public' AND p.proname = %s", (name,))[0]
        assert count == 1, (name, count)

# Other test files reuse these video names, so leave nothing behind.
conn.execute("DELETE FROM public.incidents WHERE id IN (SELECT incident_id FROM public.videos WHERE id = ANY (%s))",
             (["front-door.mp4", "back-yard.mp4", "bus-stop.mp4", "lobby.mp4", "empty.mp4"],))
conn.execute("DELETE FROM public.model_runs WHERE id LIKE 'run-%%-%%'")

conn.close()
print(f"\n{len(PASSED)} passed")
sys.exit(0)
