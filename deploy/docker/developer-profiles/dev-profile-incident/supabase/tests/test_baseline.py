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

    @test("schema: 9 tables (incidents, video_analyses, incident_match_suggestions added), no views, no legacy report tables or functions")
    def _():
        kinds = dict(conn.execute("SELECT relkind::TEXT, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                  "WHERE n.nspname = 'public' AND relkind IN ('r','v') GROUP BY 1").fetchall())
        assert kinds == {"r": 9}, kinds
        assert sorted(tables) == ["evidence_crops", "incident_match_suggestions", "incidents", "model_runs", "queries", "query_results", "report_revisions", "video_analyses", "videos"], tables
        names = " ".join(tables + functions)
        for gone in ("reports", "entities", "instruments", "assets", "human_reports", "review_status",
                     "gt_incidents", "severity_eval_log", "insert_incident", "save_human_report_edit",
                     "select_official_report", "set_review_status", "effective_incidents",
                     "search_evidence_items", "apply_r2_rename", "search_report_revisions"):
            assert gone not in names, gone
        for present in ("report_revisions_append_only", "evidence_image", "searchable_revision_id", "replace_video_crops",
                        "set_revision_crops"):
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
