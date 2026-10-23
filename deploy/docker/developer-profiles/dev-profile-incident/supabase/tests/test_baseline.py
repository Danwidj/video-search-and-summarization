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
REVISION_MIGRATIONS = [path for path in MIGRATIONS if path.name.startswith("2026102300")]
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

    @test("schema: 6 tables, no views, no legacy report tables or functions")
    def _():
        kinds = dict(conn.execute("SELECT relkind::TEXT, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                  "WHERE n.nspname = 'public' AND relkind IN ('r','v') GROUP BY 1").fetchall())
        assert kinds == {"r": 6}, kinds
        assert sorted(tables) == ["evidence_crops", "model_runs", "queries", "query_results", "report_revisions", "videos"], tables
        names = " ".join(tables + functions)
        for gone in ("incidents", "reports", "entities", "instruments", "assets", "human_reports", "review_status",
                     "gt_incidents", "severity_eval_log", "insert_incident", "save_human_report_edit",
                     "select_official_report", "set_review_status", "effective_incidents"):
            assert gone not in names, gone
        for present in ("save_human_revision", "set_official_revision", "search_evidence_items",
                        "list_incident_report_summaries", "get_incident_dashboard", "report_revisions_append_only"):
            assert present in names, present
        assert one(conn, "SELECT extnamespace::regnamespace::TEXT FROM pg_extension WHERE extname = 'vector'")[0] == "extensions"
        columns = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'videos'").fetchall()]
        assert "official_revision_id" in columns and "selected_model_run_id" not in columns, columns

    @test("migrations: the revision migrations can be applied again over the live shape")
    def _():
        with conn.transaction():
            for migration in REVISION_MIGRATIONS:
                conn.execute(migration.read_text())
        assert one(conn, "SELECT count(*) FROM public.report_revisions")[0] == 0

    @test("security: anon and authenticated cannot read any table or run any function")
    def _():
        for role in ("anon", "authenticated"):
            conn.execute(f"SET ROLE {role}")
            for table in tables:
                refused(conn, f"SELECT 1 FROM {table} LIMIT 1", kind=errors.InsufficientPrivilege)
            for fn in functions:
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))[0], (role, fn)
            refused(conn, "SELECT public.save_human_revision('v', 1, 'x', NULL, '{}', '[]', 'assault', 3, 0, 1)",
                    kind=errors.InsufficientPrivilege)
            refused(conn, "SELECT public.set_official_revision('v', NULL)", kind=errors.InsufficientPrivilege)
            refused(conn, "SELECT public.list_incident_report_summaries()", kind=errors.InsufficientPrivilege)
            refused(conn, "SELECT public.get_incident_dashboard()", kind=errors.InsufficientPrivilege)
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
    for video in ("v1", "v2", "v3", "v4"):
        conn.execute("INSERT INTO public.videos (id, filepath, source) VALUES (%s, %s, 'cam')", (video, f"uploads/{video}/clip.mp4"))
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

    crops = [
        crop("entity", "E1", "evidence/v1/u1/E1.jpg", vector(0), bounding_box=[1, 2, 300, 400],
             timestamp_seconds=3, item_name="human", description="Man in a red jacket"),
        crop("instrument", "I1", "evidence/v1/u2/I1.jpg", vector(1), item_name="bottle",
             description="Glass bottle", threat_level=3, holder_entity_id="E1"),
        crop("asset", "A1", None, vector(2), item_name="bench", description="Bus stop bench"),
    ]

    @test("set_official_revision stores the caller's crops and the pointer")
    def _():
        result = one(conn, "SELECT public.set_official_revision(%s, %s, %s)", ("v1", ai1, json.dumps(crops)))[0]
        assert result == {"videoId": "v1", "officialRevisionId": ai1, "crops": 2}, result
        rows = conn.execute("""SELECT item_type, item_id, item_name, threat_level, holder_entity_id, timestamp_seconds,
            bounding_box, image, embedding IS NOT NULL FROM public.evidence_crops ORDER BY item_type""").fetchall()
        assert rows == [
            ("entity", "E1", "human", None, None, 3, [1, 2, 300, 400], "evidence/v1/u1/E1.jpg", True),
            ("instrument", "I1", "bottle", 3, "E1", 0, [0, 0, 1000, 1000], "evidence/v1/u2/I1.jpg", True),
        ], rows
        assert one(conn, "SELECT official_revision_id FROM public.videos WHERE id = 'v1'")[0] == ai1

    @test("search_evidence_items finds the official revision's embedded crops")
    def _():
        rows = conn.execute("""SELECT incident_id, revision_id, model_run_id, item_id, incident_type,
            incident_start_timestamp FROM public.search_evidence_items(%s::extensions.vector, 5, 0.0)""",
                            (vector_literal(0),)).fetchall()
        assert rows == [("v1", ai1, "m1", "E1", "assault", "2"), ("v1", ai1, "m1", "I1", "assault", "2")], rows

    @test("marking another revision official replaces the crops; NULL clears both")
    def _():
        one_crop = [crop("entity", "E1", "evidence/v1/u3/E1.jpg", vector(0), item_name="animal",
                         description="Edited", timestamp_seconds=1)]
        result = one(conn, "SELECT public.set_official_revision(%s, %s, %s)",
                     ("v1", human["revisionId"], json.dumps(one_crop)))[0]
        assert result["crops"] == 1, result
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (ai1,))[0] == 0
        assert one(conn, "SELECT official_revision_id FROM public.videos WHERE id = 'v1'")[0] == human["revisionId"]
        cleared = one(conn, "SELECT public.set_official_revision('v1', NULL)")[0]
        assert cleared == {"videoId": "v1", "officialRevisionId": None, "crops": 0}, cleared
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 0
        assert one(conn, "SELECT official_revision_id FROM public.videos WHERE id = 'v1'")[0] is None
        refused(conn, "SELECT public.set_official_revision('v1', %s)", (ai2,), contains="Revision not found for this video")
        refused(conn, "SELECT public.set_official_revision('nope', NULL)", None, contains="Video not found")
        refused(conn, "SELECT public.set_official_revision('v1', %s, '{}')", (ai1,), contains="crops must be a list")

    conn.execute("SELECT public.set_official_revision(%s, %s, %s)", ("v1", ai1, json.dumps(crops)))

    def summaries(**kwargs):
        named = ", ".join(f"{key} => %({key})s" for key in kwargs)
        return one(conn, f"SELECT public.list_incident_report_summaries({named})", kwargs)[0]

    @test("the library shows the official revision, else the newest, one card per incident")
    def _():
        result = summaries()
        cards = {item["videoId"]: item for item in result["reports"]}
        assert result["totalItems"] == 3 and set(cards) == {"v1", "v2", "v3"}, result
        assert cards["v1"]["revisionId"] == ai1 and cards["v1"]["isOfficial"] and cards["v1"]["kind"] == "ai", cards["v1"]
        assert cards["v1"]["title"] == "Fight at the bus stop" and cards["v1"]["model"] == "model-a"
        assert cards["v1"]["outcome"] == "valid_first_pass", cards["v1"]
        assert cards["v2"]["revisionId"] == ai2 and not cards["v2"]["isOfficial"] and cards["v2"]["outcome"] == "legacy", cards["v2"]
        assert result["incidentTypes"] == ["assault", "burglary"], result["incidentTypes"]

    @test("the library filters by scope, kind, type, evidence and search")
    def _():
        assert [r["videoId"] for r in summaries(p_scope="official")["reports"]] == ["v1"]
        assert summaries(p_kind="human")["totalItems"] == 1  # only v3's newest card is human
        assert [r["videoId"] for r in summaries(p_type="burglary")["reports"]] == ["v2"]
        assert summaries(p_entities=["red jacket"])["totalItems"] == 3
        assert [r["videoId"] for r in summaries(p_search="break-in")["reports"]] == ["v2"]
        assert summaries(p_instruments=["Bottle"], p_evidence_match="exact")["totalItems"] == 3
        assert [r["videoId"] for r in summaries(p_sort="severity-low", p_scope="official")["reports"]] == ["v1"]
        conn.execute("SELECT public.set_official_revision('v1', NULL)")
        cards = {item["videoId"]: item for item in summaries()["reports"]}
        assert cards["v1"]["revisionId"] == human["revisionId"] and cards["v1"]["kind"] == "human", cards["v1"]
        assert sorted(r["videoId"] for r in summaries(p_kind="human")["reports"]) == ["v1", "v3"]
        conn.execute("SELECT public.set_official_revision(%s, %s, %s)", ("v1", ai1, json.dumps(crops)))

    @test("the dashboard counts official revisions only")
    def _():
        dashboard = one(conn, "SELECT public.get_incident_dashboard()")[0]
        assert dashboard["total"] == 1 and dashboard["revisions"] == {"ai": 1, "human": 0}, dashboard
        assert dashboard["videos"] == {"uploaded": 4, "withOfficial": 1, "awaitingSelection": 2, "withoutReport": 1}, dashboard["videos"]
        assert dashboard["types"][0]["type"] == "assault" and dashboard["topInstruments"] == [{"label": "bottle", "count": 1}], dashboard
        assert dashboard["threatLevels"] == [{"level": 3, "count": 1}] and dashboard["averageConfidence"] == 0.8, dashboard
        coverage = {row["model"]: row for row in dashboard["modelCoverage"]}
        assert coverage["model-a"]["withReport"] == 2 and coverage["model-b"]["legacy"] == 1, coverage

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

print(f"\n{len(PASSED)} passed")
sys.exit(0)
