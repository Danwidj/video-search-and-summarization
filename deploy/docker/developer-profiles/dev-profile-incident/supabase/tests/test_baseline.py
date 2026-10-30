# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests of the finals schema on a throwaway Postgres (no Supabase, no network).

    cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py

Applies every file in supabase/migrations/ in order (the finals baseline, then the report-revision
schema, then its functions). pgserver ships Postgres 16 with pgvector. supabase_stub.sql adds the
API roles and Supabase's default grants, so the lockdown is tested against what a new project
really starts with. Writes go through SET ROLE service_role, the role PostgREST uses with the
service key.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg
from psycopg import errors

HERE = Path(__file__).resolve().parent
MIGRATIONS = sorted((HERE.parent / "migrations").glob("*.sql"))
# Migrations from the revision era that can be re-applied idempotently (before the mvp3 core migration).
REVISION_MIGRATIONS = [path for path in MIGRATIONS if "20261023" <= path.name < "20261030"]
PASSED: list[str] = []


def test(name):
    def wrap(fn):
        fn()
        PASSED.append(name)
        print("ok  ", name)
    return wrap


def expect_error(conn: psycopg.Connection, sql: str, params=None, kind=errors.Error, contains: str = "") -> str:
    with conn.transaction(force_rollback=True):
        try:
            conn.execute(sql, params)
        except kind as exc:
            assert contains in str(exc), (contains, str(exc))
            raise _Expected(str(exc))
    raise AssertionError(f"no error from: {sql}")


class _Expected(Exception):
    pass


def refused(conn, sql, params=None, kind=errors.Error, contains=""):
    try:
        expect_error(conn, sql, params, kind, contains)
    except _Expected as exc:
        return str(exc)


def one(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()


def vector(index: int = 0) -> list[float]:
    values = [0.0] * 1024
    values[index] = 1.0
    return values


def vector_literal(index: int = 0) -> str:
    return json.dumps(vector(index))


def report(kind="assault", severity=4, start=2, end=9, title="Fight at the bus stop", entity="Man in a red jacket"):
    return {
        "incident": {"type": kind, "title": title, "start_timestamp": start, "end_timestamp": end, "duration": end - start,
                     "description": "Two people fight.", "severity_level": severity,
                     "confidence_score": 0.8, "location": None},
        "entities": [{"entity_id": "E1", "type": "human", "description": entity, "timestamp_seconds": 3, "label": "man"}],
        "instruments": [{"instrument_id": "I1", "entity_id": "E1", "name": "bottle", "description": "Glass bottle",
                         "threat_level": 3, "timestamp_seconds": 4, "label": "bottle"}],
        "assets": [{"asset_id": "A1", "name": "bench", "description": "Bus stop bench", "timestamp_seconds": 5, "label": "bench"}],
        "timeline": [],
        "uncertainties": [],
    }


EVIDENCE = [
    {"item_type": "entity", "item_id": "E1", "image": "evidence/v1/u1/E1.jpg", "bounding_box": [1, 2, 300, 400], "timestamp_seconds": 3},
    {"item_type": "instrument", "item_id": "I1", "image": "evidence/v1/u2/I1.jpg", "bounding_box": None, "timestamp_seconds": None, "source": "upload"},
    {"item_type": "asset", "item_id": "A1", "image": None, "bounding_box": None, "timestamp_seconds": 5},
]


def crop(item_type: str, item_id: str, image: str, embedding: list[float] | None, **fields) -> dict:
    return {"item_type": item_type, "item_id": item_id, "image": image, "bounding_box": fields.get("bounding_box"),
            "timestamp_seconds": fields.get("timestamp_seconds"), "item_name": fields.get("item_name"),
            "description": fields.get("description"), "threat_level": fields.get("threat_level"),
            "holder_entity_id": fields.get("holder_entity_id"), "embedding": embedding}


with tempfile.TemporaryDirectory() as tmp:
    server = pgserver.get_server(tmp, cleanup_mode="stop")
    conn = psycopg.connect(server.get_uri(), autocommit=True)
    conn.execute((HERE / "supabase_stub.sql").read_text())
    with conn.transaction():
        for migration in MIGRATIONS:
            conn.execute(migration.read_text())

    tables = [r[0] for r in conn.execute(
        "SELECT c.oid::regclass::TEXT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v') ORDER BY 1").fetchall()]
    functions = [r[0] for r in conn.execute(
        "SELECT p.oid::regprocedure::TEXT FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') ORDER BY 1").fetchall()]

    @test("schema: 7 tables (incidents added), no views, no legacy report tables or functions")
    def _():
        kinds = dict(conn.execute("SELECT relkind::TEXT, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                  "WHERE n.nspname = 'public' AND relkind IN ('r','v') GROUP BY 1").fetchall())
        assert kinds == {"r": 7}, kinds
        assert sorted(tables) == ["evidence_crops", "incidents", "model_runs", "queries", "query_results", "report_revisions", "videos"], tables
        names = " ".join(tables + functions)
        for gone in ("reports", "entities", "instruments", "assets", "human_reports", "review_status",
                     "gt_incidents", "severity_eval_log", "insert_incident", "save_human_report_edit",
                     "select_official_report", "set_review_status", "effective_incidents",
                     "set_official_revision", "searchable_revision_id", "replace_video_crops",
                     "set_revision_crops", "search_evidence_items", "list_incident_report_summaries",
                     "get_incident_dashboard", "save_human_revision_with_crops"):
            assert gone not in names, gone
        for present in ("save_human_revision", "report_revisions_append_only",
                        "apply_r2_rename", "search_report_revisions", "evidence_image"):
            assert present in names, present
        assert one(conn, "SELECT extnamespace::regnamespace::TEXT FROM pg_extension WHERE extname = 'vector'")[0] == "extensions"
        vid_cols = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'videos'").fetchall()]
        assert "incident_id" in vid_cols and "recorded_at" in vid_cols, vid_cols
        assert "official_revision_id" not in vid_cols and "official_since" not in vid_cols, vid_cols
        assert "selected_model_run_id" not in vid_cols, vid_cols
        vid_id_type = one(conn, "SELECT data_type FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='videos' AND column_name='id'")[0]
        run_id_type = one(conn, "SELECT data_type FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='model_runs' AND column_name='id'")[0]
        assert vid_id_type == "text", vid_id_type
        assert run_id_type == "text", run_id_type

    @test("security: anon and authenticated cannot read any table or run any function")
    def _():
        for role in ("anon", "authenticated"):
            conn.execute("RESET ROLE")
            for table in tables:
                assert not one(conn, "SELECT has_table_privilege(%s, %s, 'SELECT')", (role, table))[0], (role, table)
            for fn in functions:
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))[0], (role, fn)
            conn.execute(f"SET ROLE {role}")
            refused(conn, "SELECT public.save_human_revision('v', 1, 'x', NULL, '{}', '[]', 'assault', 3, 0, 1)",
                    kind=errors.InsufficientPrivilege)
            conn.execute("RESET ROLE")

    @test("security: objects created later in public are not exposed either (default privileges)")
    def _():
        conn.execute("CREATE TABLE public.zz_later (id INT)")
        conn.execute("CREATE FUNCTION public.zz_later_fn() RETURNS INT LANGUAGE sql AS 'SELECT 1'")
        try:
            for role in ("anon", "authenticated"):
                assert not one(conn, "SELECT has_table_privilege(%s, 'public.zz_later', 'SELECT')", (role,))[0]
                assert not one(conn, "SELECT has_function_privilege(%s, 'public.zz_later_fn()', 'EXECUTE')", (role,))[0]
            assert one(conn, "SELECT has_table_privilege('service_role', 'public.zz_later', 'SELECT')")[0]
            assert one(conn, "SELECT has_function_privilege('service_role', 'public.zz_later_fn()', 'EXECUTE')")[0]
        finally:
            conn.execute("DROP TABLE public.zz_later; DROP FUNCTION public.zz_later_fn()")

    @test("security: tests/security_check.sql reports nothing")
    def _():
        rows = conn.execute((HERE / "security_check.sql").read_text()).fetchall()
        assert rows == [], rows

    conn.execute("SET ROLE service_role")
    # Each video requires an incident (mvp3: official pointer lives on the incident).
    # One shared incident covers the four baseline test videos.
    (base_incident_id,) = conn.execute(
        "INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()
    for video in ("v1", "v2", "v3", "v4"):
        conn.execute(
            "INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
            (video, f"uploads/{video}/clip.mp4", base_incident_id))
    conn.execute("INSERT INTO public.model_runs (id, model_name, notes) VALUES ('m1', 'model-a', %s), ('m2', 'model-b', NULL)",
                 (json.dumps({"incidentConsoleV2": {"contractVersion": "incident-contract-v3", "status": "valid_first_pass"}}),))

    def ai_revision(video: str, revision_no: int, run: str, payload: dict, evidence: list) -> int:
        inc = payload["incident"]
        return one(conn, """
            INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds)
            VALUES (%s, %s, 'ai', %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (video, revision_no, run, json.dumps(payload), json.dumps(evidence), inc["type"], inc["severity_level"],
             inc["start_timestamp"], inc["end_timestamp"]))[0]

    ai1 = ai_revision("v1", 1, "m1", report(), EVIDENCE)
    ai2 = ai_revision("v2", 1, "m2", report(kind="burglary", severity=2, title="Shop break-in"), [])

    def save(video, parent, payload, evidence, by="Dana", note=None, incident_type=None, severity=None,
             start=None, end=None):
        incident = payload["incident"]
        return one(conn, """
            SELECT public.save_human_revision(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (video, parent, by, note, json.dumps(payload), json.dumps(evidence),
             incident_type if incident_type is not None else incident["type"],
             severity if severity is not None else incident["severity_level"],
             start if start is not None else incident["start_timestamp"],
             end if end is not None else incident["end_timestamp"]))[0]

    human = save("v1", ai1, report(kind="explosion", severity=5, start=1, end=8, entity="Woman in a coat"),
                 EVIDENCE, note=" fixed type ", incident_type="explosion", severity=5, start=1, end=8)

    @test("save_human_revision appends the next revision with the caller's facets and parent run")
    def _():
        assert human["revisionNo"] == 2 and human["kind"] == "human" and human["parentId"] == ai1, human
        assert human["modelRunId"] == "m1" and human["createdBy"] == "Dana" and human["note"] == "fixed type", human
        row = one(conn, "SELECT incident_type, severity_level, start_seconds, end_seconds, created_by, kind FROM public.report_revisions WHERE id = %s",
                  (human["revisionId"],))
        assert row == ("explosion", 5, 1, 8, "Dana", "human"), row

    @test("save_human_revision hands out one revision_no at a time per video")
    def _():
        first = save("v3", ai_revision("v3", 1, "m1", report(), []), report(), [])
        second = save("v3", first["revisionId"], report(), [])
        assert (first["revisionNo"], second["revisionNo"]) == (2, 3), (first, second)
        assert second["parentId"] == first["revisionId"], second
        assert [r[0] for r in conn.execute("SELECT revision_no FROM public.report_revisions WHERE video_id = 'v3' ORDER BY 1").fetchall()] == [1, 2, 3]

    @test("save_human_revision refuses a bad parent, name, payload or evidence")
    def _():
        args = "SELECT public.save_human_revision(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        refused(conn, args, ("v1", ai2, "Dana", None, json.dumps(report()), "[]", "assault", 4, 2, 9),
                contains="Revision not found for this video")
        refused(conn, args, ("nope", ai1, "Dana", None, json.dumps(report()), "[]", "assault", 4, 2, 9),
                contains="Video not found")
        refused(conn, args, ("v1", None, "Dana", None, json.dumps(report()), "[]", "assault", 4, 2, 9),
                contains="parent revision")
        refused(conn, args, ("v1", ai1, "  ", None, json.dumps(report()), "[]", "assault", 4, 2, 9),
                contains="reviewer name")
        refused(conn, args, ("v1", ai1, "Dana", None, json.dumps({"entities": []}), "[]", "assault", 4, 2, 9),
                contains="incident")
        refused(conn, args, ("v1", ai1, "Dana", None, json.dumps(report()), "{}", "assault", 4, 2, 9),
                contains="evidence must be a list")

    @test("revisions are append-only")
    def _():
        refused(conn, "UPDATE public.report_revisions SET note = 'x' WHERE id = %s", (ai1,), contains="append-only")
        refused(conn, "DELETE FROM public.report_revisions WHERE id = %s", (ai1,), contains="append-only")

    @test("apply_r2_rename points a video, its evidence and its crops at renamed keys and nothing else")
    def _():
        (r10_inc,) = conn.execute("INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()
        conn.execute("INSERT INTO public.videos (id, filepath, source, incident_id) VALUES ('v10', 'uploads/cam/0123.mp4', 'cam', %s)", (r10_inc,))
        evidence = [
            {"item_type": "entity", "item_id": "E1", "image": "evidence/old/E1.jpg"},
            {"item_type": "asset", "item_id": "A1", "image": None},
            {"item_type": "instrument", "item_id": "I1", "image": "evidence/old/I1.jpg"},
        ]
        rev = ai_revision("v10", 1, "m1", report(), evidence)
        for item_type, item_id, image in (("entity", "E1", "evidence/old/E1.jpg"), ("instrument", "I1", "evidence/old/I1.jpg")):
            conn.execute("""INSERT INTO public.evidence_crops (revision_id, item_type, item_id, item_name, description, timestamp_seconds, bounding_box, image)
                            VALUES (%s, %s, %s, 'n', 'd', 1, '{1,2,3,4}', %s)""", (rev, item_type, item_id, image))
        before = one(conn, "SELECT payload, note, created_at FROM public.report_revisions WHERE id = %s", (rev,))
        notes = one(conn, "SELECT notes FROM public.model_runs WHERE id = 'm1'")[0]
        key_map = json.dumps({"evidence/old/E1.jpg": "evidence/Clip.mp4/run-1/E1.jpg", "evidence/old/I1.jpg": "evidence/Clip.mp4/run-1/I1.jpg"})
        result = one(conn, "SELECT public.apply_r2_rename('v10', 'uploads/Clip.mp4', %s)", (key_map,))[0]
        assert result == {"videoId": "v10", "filepath": "uploads/Clip.mp4", "revisions": 1, "crops": 2}, result
        assert one(conn, "SELECT filepath FROM public.videos WHERE id = 'v10'")[0] == "uploads/Clip.mp4"
        row = one(conn, "SELECT evidence, payload, note, created_at FROM public.report_revisions WHERE id = %s", (rev,))
        assert [e["image"] for e in row[0]] == ["evidence/Clip.mp4/run-1/E1.jpg", None, "evidence/Clip.mp4/run-1/I1.jpg"], row[0]
        assert [e["item_id"] for e in row[0]] == ["E1", "A1", "I1"], "evidence order is kept"
        assert (row[1], row[2], row[3]) == before, "only the evidence column of a revision changes"
        images = sorted(r[0] for r in conn.execute("SELECT image FROM public.evidence_crops WHERE revision_id = %s", (rev,)).fetchall())
        assert images == ["evidence/Clip.mp4/run-1/E1.jpg", "evidence/Clip.mp4/run-1/I1.jpg"], images
        assert one(conn, "SELECT notes FROM public.model_runs WHERE id = 'm1'")[0] == notes, "model_runs.notes is immutable"
        again = one(conn, "SELECT public.apply_r2_rename('v10', 'uploads/Clip.mp4', %s)", (key_map,))[0]
        assert again["revisions"] == 0 and again["crops"] == 0, "running it again changes nothing"
        other = one(conn, "SELECT evidence FROM public.report_revisions WHERE video_id = 'v2'")[0]
        assert other == [], other

    @test("apply_r2_rename leaves the append-only guard in force and refuses bad input")
    def _():
        refused(conn, "UPDATE public.report_revisions SET evidence = '[]' WHERE video_id = 'v10'", contains="append-only")
        refused(conn, "UPDATE public.report_revisions SET note = 'x' WHERE video_id = 'v10'", contains="append-only")
        refused(conn, "DELETE FROM public.report_revisions WHERE video_id = 'v10'", contains="append-only")
        refused(conn, "SELECT public.apply_r2_rename('v10', NULL, '[]')", contains="object")
        refused(conn, "SELECT public.apply_r2_rename('v10', NULL, '{\"a\": 1}')", contains="string")
        refused(conn, "SELECT public.apply_r2_rename('nope', 'uploads/x.mp4', '{}')", contains="Video not found")
        assert one(conn, "SELECT current_setting('app.r2_rename', true)")[0] in (None, "", "off")
        conn.execute("DELETE FROM public.videos WHERE id = 'v10'")
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE video_id = 'v10'")[0] == 0

    @test("security: apply_r2_rename is for the service role only")
    def _():
        conn.execute("RESET ROLE")
        sig = "public.apply_r2_rename(character varying, text, jsonb)"
        for role in ("anon", "authenticated"):
            assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))[0], role
        assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,))[0]
        conn.execute("SET ROLE service_role")

    @test("search_report_revisions ranks embedded revisions and skips NULL vectors")
    def _():
        (r89_inc,) = conn.execute("INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()
        conn.execute("INSERT INTO public.videos (id, incident_id) VALUES ('v8', %s), ('v9', %s)", (r89_inc, r89_inc))
        embedded = one(conn, """
            INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds, embedding)
            VALUES ('v8', 1, 'ai', 'm1', %s, '[]', 'assault', 4, 2, 9, %s::extensions.vector) RETURNING id""",
            (json.dumps(report(title="Vector hit")), vector_literal(7)))[0]
        ai_revision("v9", 1, "m1", report(title="No vector"), [])
        rows = conn.execute("""SELECT revision_id, video_id, title, similarity_score FROM public.search_report_revisions(%s::extensions.vector, 5, 0.0)""",
                            (vector_literal(7),)).fetchall()
        assert rows == [(embedded, "v8", "Vector hit", 1.0)], rows
        assert conn.execute("SELECT count(*) FROM public.search_report_revisions(%s::extensions.vector, 5, 1.1)",
                            (vector_literal(7),)).fetchone()[0] == 0
        refused(conn, "UPDATE public.report_revisions SET embedding = NULL WHERE id = %s", (embedded,), contains="append-only")
        assert one(conn, "SELECT count(*) FROM pg_indexes WHERE indexname = 'report_revisions_embedding_hnsw_idx'")[0] == 1

    @test("deleting a video removes its revisions, crops and query results")
    def _():
        conn.execute("INSERT INTO public.queries (id, query_text) VALUES ('q1', 'man')")
        conn.execute("""INSERT INTO public.query_results (id, query_id, revision_id, item_type, item_id, rank, similarity_score, critic_verdict)
                        VALUES ('r1', 'q1', %s, 'entity', 'E1', 1, 0.9, 'confirmed')""", (ai1,))
        conn.execute("DELETE FROM public.videos WHERE id = 'v1'")
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE video_id = 'v1'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.query_results")[0] == 0

    conn.execute("RESET ROLE")
    conn.close()

    # Discover and run every other test_*.py in this directory.
    # Each sub-test connects via PGSERVER_URI and runs independently.
    import os
    import subprocess
    server_uri = server.get_uri()
    for test_file in sorted(HERE.glob("test_*.py")):
        if test_file.name == Path(__file__).name:
            continue
        env = os.environ.copy()
        env["PGSERVER_URI"] = server_uri
        result = subprocess.run([sys.executable, str(test_file)], env=env)
        if result.returncode != 0:
            print(f"\nFAIL: {test_file.name}", file=sys.stderr)
            sys.exit(result.returncode)

print(f"\n{len(PASSED)} passed")
sys.exit(0)
