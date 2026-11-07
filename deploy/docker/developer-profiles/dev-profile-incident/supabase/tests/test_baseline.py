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
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pgserver
import psycopg
from psycopg import errors

HERE = Path(__file__).resolve().parent
MIGRATIONS = sorted((HERE.parent / "migrations").glob("*.sql"))
REVISION_MIGRATIONS = [path for path in MIGRATIONS if path.name >= "20261023"]
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
            "slice_start_seconds": fields.get("slice_start_seconds"), "slice_end_seconds": fields.get("slice_end_seconds"),
            "frame": fields.get("frame"),
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

    @test("schema: 7 tables, no views, no legacy report tables or functions")
    def _():
        kinds = dict(conn.execute("SELECT relkind::TEXT, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                  "WHERE n.nspname = 'public' AND relkind IN ('r','v') GROUP BY 1").fetchall())
        assert kinds == {"r": 7}, kinds
        assert sorted(tables) == ["analysis_jobs", "evidence_crops", "model_runs", "queries", "query_results",
                                  "report_revisions", "videos"], tables
        names = " ".join(tables + functions)
        for gone in ("incidents", "reports", "entities", "instruments", "assets", "human_reports", "review_status",
                     "gt_incidents", "severity_eval_log", "insert_incident", "save_human_report_edit",
                     "select_official_report", "set_review_status", "effective_incidents"):
            assert gone not in names, gone
        for present in ("save_human_revision", "set_official_revision", "search_evidence_items",
                        "list_incident_report_summaries", "get_incident_dashboard", "report_revisions_append_only",
                        "set_revision_crops", "searchable_revision_id", "evidence_slice", "list_revisions_missing_crops",
                        "set_revision_embedding", "list_revisions_missing_embeddings", "repair_revision_crops",
                        "refresh_revision_embedding", "claim_analysis_job", "touch_analysis_job",
                        "finish_analysis_job", "retry_analysis_job", "cancel_analysis_job"):
            assert present in names, present
        assert one(conn, "SELECT extnamespace::regnamespace::TEXT FROM pg_extension WHERE extname = 'vector'")[0] == "extensions"
        columns = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'videos'").fetchall()]
        assert "official_revision_id" in columns and "selected_model_run_id" not in columns, columns
        assert "official_since" in columns, columns

    @test("migrations: the revision migrations can be applied again over the live shape")
    def _():
        with conn.transaction():
            for migration in REVISION_MIGRATIONS:
                conn.execute(migration.read_text())
        assert one(conn, "SELECT count(*) FROM public.report_revisions")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.analysis_jobs")[0] == 0

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

    @test("security: the dashboard has one signature, for the service role only")
    def _():
        rows = conn.execute("SELECT oid::regprocedure::text, has_function_privilege('anon', oid, 'EXECUTE'), has_function_privilege('authenticated', oid, 'EXECUTE'), has_function_privilege('service_role', oid, 'EXECUTE') FROM pg_proc WHERE proname = 'get_incident_dashboard'").fetchall()
        assert len(rows) == 1 and rows[0][1:] == (False, False, True), rows

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

    @test("marking another revision official replaces the crops; NULL leaves the newest revision searchable")
    def _():
        one_crop = [crop("entity", "E1", "evidence/v1/u3/E1.jpg", vector(0), item_name="animal",
                         description="Edited", timestamp_seconds=1)]
        result = one(conn, "SELECT public.set_official_revision(%s, %s, %s)",
                     ("v1", human["revisionId"], json.dumps(one_crop)))[0]
        assert result["crops"] == 1, result
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (ai1,))[0] == 0
        assert one(conn, "SELECT official_revision_id FROM public.videos WHERE id = 'v1'")[0] == human["revisionId"]
        cleared = one(conn, "SELECT public.set_official_revision('v1', NULL)")[0]
        # the edited revision is also v1's newest, so it stays searchable and keeps its row
        assert cleared == {"videoId": "v1", "officialRevisionId": None, "crops": 1}, cleared
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (human["revisionId"],))[0] == 1
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 1
        assert one(conn, "SELECT official_revision_id FROM public.videos WHERE id = 'v1'")[0] is None
        refused(conn, "SELECT public.set_official_revision('v1', %s)", (ai2,), contains="Revision not found for this video")
        refused(conn, "SELECT public.set_official_revision('nope', NULL)", None, contains="Video not found")
        refused(conn, "SELECT public.set_official_revision('v1', %s, '{}')", (ai1,), contains="crops must be a list")

    conn.execute("SELECT public.set_official_revision(%s, %s, %s)", ("v1", ai1, json.dumps(crops)))

    def summaries(**kwargs):
        named = ", ".join(f"{key} => %({key})s" for key in kwargs)
        return one(conn, f"SELECT public.list_incident_report_summaries({named})", kwargs)[0]

    @test("the library's official-first sort lists official reports, then the rest, each by upload date oldest first, across pages")
    def _():
        with conn.transaction(force_rollback=True):
            # v1 is official and uploaded last; v2 and v3 are not yet official.
            conn.execute("UPDATE public.videos SET uploaded_datetime = '2026-03-03' WHERE id = 'v1'")
            conn.execute("UPDATE public.videos SET uploaded_datetime = '2026-02-02' WHERE id = 'v2'")
            conn.execute("UPDATE public.videos SET uploaded_datetime = '2026-01-01' WHERE id = 'v3'")
            order = lambda **kw: [r["videoId"] for r in summaries(p_sort="official-first", **kw)["reports"]]
            assert order() == ["v1", "v3", "v2"], order()
            assert order(p_page_size=2, p_page=1) == ["v1", "v3"] and order(p_page_size=2, p_page=2) == ["v2"]
            assert summaries(p_sort="official-first")["totalItems"] == 3
            assert order(p_scope="not_official") == ["v3", "v2"], "the filters still apply"
            assert [r["videoId"] for r in summaries(p_sort="oldest")["reports"]] != order(), "other sorts are unchanged"

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
        assert sorted(r["videoId"] for r in summaries(p_scope="not_official")["reports"]) == ["v2", "v3"]
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

    def dashboard_of(**kwargs):
        kwargs.setdefault("p_scope", "all")
        named = ", ".join(f"{key} => %({key})s" for key in kwargs)
        return one(conn, f"SELECT public.get_incident_dashboard({named})", kwargs)[0]

    @test("the dashboard counts each video once: official, else newest, and reports the split")
    def _():
        dashboard = dashboard_of()
        assert dashboard["total"] == 3 and (dashboard["official"], dashboard["notOfficial"]) == (1, 2), dashboard
        assert dashboard["revisions"] == {"ai": 2, "human": 1}, dashboard
        assert dashboard["videos"] == {"uploaded": 4, "withOfficial": 1, "awaitingSelection": 2, "withoutReport": 1}, dashboard["videos"]
        assert {t["type"]: (t["count"], t["official"], t["notOfficial"]) for t in dashboard["types"]} == {"assault": (2, 1, 1), "burglary": (1, 0, 1)}, dashboard["types"]
        assert dashboard["topInstruments"] == [{"label": "bottle", "count": 3, "official": 1, "notOfficial": 2}], dashboard["topInstruments"]
        assert dashboard["threatLevels"] == [{"level": 3, "count": 3}] and abs(dashboard["averageConfidence"] - 0.8) < 1e-9, dashboard
        by_scope = dashboard["severityByScope"]
        for band in ("low", "medium", "high"):
            assert by_scope["official"][band] + by_scope["notOfficial"][band] == dashboard["severity"][band], dashboard
        assert sum(day["official"] for day in dashboard["trend"]) == 1 and sum(day["notOfficial"] for day in dashboard["trend"]) == 2, dashboard["trend"]
        assert sum(cell["official"] for cell in dashboard["heatmap"]) == 1 and sum(cell["notOfficial"] for cell in dashboard["heatmap"]) == 2, dashboard["heatmap"]
        assert all(asset["official"] + asset["notOfficial"] == asset["count"] for asset in dashboard["topAssets"]), dashboard["topAssets"]
        coverage = {row["model"]: row for row in dashboard["modelCoverage"]}
        assert coverage["model-a"]["withReport"] == 2 and coverage["model-b"]["legacy"] == 1, coverage

    @test("dashboard ties between equal counts are broken in byte order (COLLATE \"C\"), whatever the database collation")
    def _():
        definition = one(conn, "SELECT pg_get_functiondef('public.get_incident_dashboard'::regproc)")[0]
        tie_breaks = re.findall(r"ORDER BY [^)\n]*?\b(?:label|incident_type|model_name)\b[^)\n]*", definition)
        assert len(tie_breaks) >= 11, tie_breaks
        assert all('COLLATE "C"' in clause for clause in tie_breaks), [c for c in tie_breaks if 'COLLATE "C"' not in c]

    @test("every dashboard number equals the total of the library list it opens")
    def _():
        dashboard = dashboard_of()
        assert summaries()["totalItems"] == dashboard["total"]
        assert summaries(p_scope="official")["totalItems"] == dashboard["official"]
        assert summaries(p_scope="not_official")["totalItems"] == dashboard["notOfficial"]
        for item in dashboard["types"]:
            assert summaries(p_type=item["type"])["totalItems"] == item["count"], item
            assert summaries(p_type=item["type"], p_scope="official")["totalItems"] == item["official"], item
        for band, count in dashboard["severity"].items():
            assert summaries(p_severity=band)["totalItems"] == count, band
        for asset in dashboard["topAssets"]:
            assert summaries(p_assets=[asset["label"]], p_evidence_match="exact")["totalItems"] == asset["count"], asset
        for kind, count in dashboard["revisions"].items():
            assert summaries(p_kind=kind)["totalItems"] == count, kind

    @test("the dashboard counts the counted reports whose video has several versions, with the same filters")
    def _():
        # v1 has an AI and a human version, v3 three, v2 one: two counted reports have several versions.
        assert dashboard_of()["multipleVersions"] == 2, dashboard_of()["multipleVersions"]
        assert dashboard_of(p_scope="official")["multipleVersions"] == 1, "v1 only"
        assert dashboard_of(p_scope="not_official")["multipleVersions"] == 1, "v3 only; v2 has one version"
        assert dashboard_of(p_type="burglary")["multipleVersions"] == 0, "v2 has one version"
        assert dashboard_of(p_type="assault")["multipleVersions"] == 2

    @test("the dashboard counts every version of the counted reports, split AI and human, with the same filters")
    def _():
        # v1: AI + human, v2: AI, v3: AI + two human. total and revisions still count one revision per video.
        assert dashboard_of()["versions"] == {"total": 6, "ai": 3, "human": 3}, dashboard_of()["versions"]
        assert dashboard_of()["total"] == 3 and sum(dashboard_of()["revisions"].values()) == 3
        assert dashboard_of(p_scope="official")["versions"] == {"total": 2, "ai": 1, "human": 1}, "v1 only"
        assert dashboard_of(p_scope="not_official")["versions"] == {"total": 4, "ai": 2, "human": 2}, "v2 and v3"
        assert dashboard_of(p_type="burglary")["versions"] == {"total": 1, "ai": 1, "human": 0}, "v2 only"
        none = dashboard_of(p_type="burglary", p_severity="high")["versions"]
        assert none == {"total": 0, "ai": 0, "human": 0}, none

    @test("the dashboard counts evidence items by kind, split by official, for the counted reports")
    def _():
        # Each counted report carries one entity, one instrument and one asset: official v1, not yet official v2 and v3.
        everything = {row["kind"]: row for row in dashboard_of()["evidence"]}
        assert everything == {kind: {"kind": kind, "count": 3, "official": 1, "notOfficial": 2}
                              for kind in ("entities", "instruments", "assets")}, everything
        official = {row["kind"]: row["count"] for row in dashboard_of(p_scope="official")["evidence"]}
        assert official == {"entities": 1, "instruments": 1, "assets": 1}, official
        assert dashboard_of()["entityTypes"] == [{"label": "human", "count": 3, "official": 1, "notOfficial": 2}], dashboard_of()["entityTypes"]
        none = dashboard_of(p_type="burglary", p_severity="high")
        assert none["total"] == 0 and [row["count"] for row in none["evidence"]] == [0, 0, 0], none["evidence"]

    @test("the dashboard filters by report status, and leaves the video and model counts alone")
    def _():
        everything = dashboard_of()
        for scope, expected in (("all", 3), ("official", 1), ("not_official", 2)):
            dashboard = dashboard_of(p_scope=scope)
            assert dashboard["total"] == expected == summaries(p_scope=scope)["totalItems"], (scope, dashboard["total"])
            assert dashboard["videos"] == everything["videos"] and dashboard["modelCoverage"] == everything["modelCoverage"], scope
        official = dashboard_of(p_scope="official")
        assert (official["official"], official["notOfficial"]) == (1, 0), official
        assert [t["type"] for t in official["types"]] == ["assault"], official["types"]
        assert (dashboard_of(p_scope="not_official")["official"]) == 0
        assert dashboard_of(p_scope=None)["total"] == 1
        bounds = {"p_period_start": "2026-01-01 00:00:00", "p_period_end": "2099-01-01 00:00:00"}
        assert dashboard_of(**bounds, p_scope="official")["previous"]["total"] == 0, "the comparison is scoped too"

    @test("a caller that omits the report status, like a console from before it existed, sees official reports only")
    def _():
        omitted = one(conn, "SELECT public.get_incident_dashboard()")[0]
        assert omitted["total"] == 1 and omitted["revisions"] == {"ai": 1, "human": 0}, omitted
        assert [t["type"] for t in omitted["types"]] == ["assault"], omitted["types"]
        assert omitted["videos"] == dashboard_of()["videos"]

    @test("the dashboard with no official revision still counts every report and marks nothing official")
    def _():
        with conn.transaction(force_rollback=True):
            conn.execute("SELECT public.set_official_revision('v1', NULL)")
            before = conn.execute("SELECT id, official_revision_id, official_since FROM public.videos ORDER BY id").fetchall()
            dashboard = dashboard_of()
            assert dashboard["total"] == 3 and (dashboard["official"], dashboard["notOfficial"]) == (0, 3), dashboard
            assert dashboard["videos"]["withOfficial"] == 0 and dashboard["videos"]["awaitingSelection"] == 3, dashboard["videos"]
            assert conn.execute("SELECT id, official_revision_id, official_since FROM public.videos ORDER BY id").fetchall() == before
        volatility = one(conn, "SELECT provolatile FROM pg_proc WHERE proname = 'get_incident_dashboard'")[0]
        assert volatility == "s", "STABLE: the dashboard cannot write"

    @test("the dashboard's trend days are the viewer's days, like the heatmap")
    def _():
        with conn.transaction(force_rollback=True):
            # 20:00 UTC on the 30th is 04:00 on the 31st in Singapore.
            conn.execute("""INSERT INTO public.videos (id, filepath, uploaded_datetime) VALUES ('v-late', 'uploads/late.mp4', '2026-10-30 19:00:00')""")
            conn.execute("""INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds, created_at)
                VALUES ('v-late', 1, 'ai', 'm1', %s, '[]', 'assault', 3, 1, 2, '2026-10-30 20:00:00')""", (json.dumps(report()),))
            bounds = {"p_period_start": "2026-10-30 12:00:00", "p_period_end": "2026-10-30 23:00:00"}
            utc = dashboard_of(**bounds, p_timezone="UTC")
            singapore = dashboard_of(**bounds, p_timezone="Asia/Singapore")
            assert [(d["date"], d["count"]) for d in utc["trend"]] == [("2026-10-30", 1)], utc["trend"]
            assert [(d["date"], d["count"]) for d in singapore["trend"]] == [("2026-10-30", 0), ("2026-10-31", 1)], singapore["trend"]
            assert singapore["heatmap"] == [{"day": 6, "hour": 4, "count": 1, "official": 0, "notOfficial": 1}], singapore["heatmap"]

    @test("an Unclassified row opens its reports in the library")
    def _():
        with conn.transaction(force_rollback=True):
            conn.execute("""INSERT INTO public.videos (id, filepath, uploaded_datetime) VALUES ('v-none', 'uploads/none.mp4', now())""")
            conn.execute("""INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds)
                VALUES ('v-none', 1, 'ai', 'm1', %s, '[]', NULL, 3, 1, 2)""", (json.dumps(report()),))
            dashboard = dashboard_of()
            row = next(item for item in dashboard["types"] if item["type"] == "Unclassified")
            assert row["count"] == 1 and row["notOfficial"] == 1, row
            result = summaries(p_type="Unclassified")
            assert result["totalItems"] == 1 and result["reports"][0]["videoId"] == "v-none", result
            assert dashboard_of(p_type="Unclassified")["total"] == 1
            assert summaries(p_type="assault")["totalItems"] == dashboard_of(p_type="assault")["total"] == 2

    def cards():
        return {item["videoId"]: item for item in summaries()["reports"]}

    @test("library cards carry officialSince, versionCount, evidenceCount and thumbnail")
    def _():
        found = cards()
        assert found["v1"]["isOfficial"] and found["v1"]["officialSince"] is not None, found["v1"]
        assert found["v1"]["versionCount"] == 2 and found["v1"]["evidenceCount"] == 2, found["v1"]
        assert found["v1"]["thumbnail"] == "evidence/v1/u1/E1.jpg", found["v1"]
        assert found["v2"]["officialSince"] is None and found["v2"]["versionCount"] == 1, found["v2"]
        assert found["v2"]["evidenceCount"] == 0 and found["v2"]["thumbnail"] is None, found["v2"]
        assert found["v3"]["versionCount"] == 3 and found["v3"]["officialSince"] is None, found["v3"]

    @test("official_since is set when the pointer moves, kept on a repeat mark and cleared with it")
    def _():
        since = lambda: one(conn, "SELECT official_since FROM public.videos WHERE id = 'v1'")[0]
        first = since()
        conn.execute("SELECT public.set_official_revision(%s, %s, %s)", ("v1", ai1, json.dumps(crops)))
        assert since() == first, (since(), first)
        conn.execute("SELECT public.set_official_revision('v1', NULL)")
        assert since() is None
        conn.execute("SELECT public.set_official_revision(%s, %s, %s)", ("v1", ai1, json.dumps(crops)))
        assert since() is not None and since() >= first

    searchable = lambda video: one(conn, "SELECT public.searchable_revision_id(%s)", (video,))[0]
    searched = lambda index: conn.execute(
        "SELECT incident_id, revision_id, item_id FROM public.search_evidence_items(%s::extensions.vector, 5, 0.5)",
        (vector_literal(index),)).fetchall()
    crop_count = lambda video: one(
        conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id IN (SELECT id FROM public.report_revisions WHERE video_id = %s)",
        (video,))[0]
    set_crops = lambda video, revision, rows: one(conn, "SELECT public.set_revision_crops(%s, %s, %s)", (video, revision, json.dumps(rows)))[0]

    @test("the searchable revision is the official one, else the newest, else none")
    def _():
        assert searchable("v1") == ai1 and searchable("v2") == ai2 and searchable("v4") is None
        assert searchable("v3") == one(conn, "SELECT max(id) FROM public.report_revisions WHERE video_id = 'v3'")[0]

    @test("a video with no official revision becomes searchable through its newest revision")
    def _():
        assert searched(5) == []
        result = set_crops("v2", ai2, [crop("entity", "E1", "evidence/v2/u1/E1.jpg", vector(5), item_name="human", description="Burglar")])
        assert result == {"videoId": "v2", "revisionId": ai2, "crops": 1}, result
        assert searched(5) == [("v2", ai2, "E1")], searched(5)
        assert one(conn, "SELECT official_revision_id FROM public.videos WHERE id = 'v2'")[0] is None

    @test("search_evidence_items scopes to one video, and lists it in video time order with no query")
    def _():
        scoped = lambda video, index, min_similarity: conn.execute(
            """SELECT incident_id, item_id, similarity_score FROM public.search_evidence_items(
                %s::extensions.vector, 20, %s, p_video_id => %s)""",
            (vector_literal(index) if index is not None else None, min_similarity, video)).fetchall()
        # the query matches v2's crop best, but a scoped search still returns only the scoped video's rows
        assert {row[0] for row in scoped("v1", 5, -1.0)} == {"v1"}
        assert {row[0] for row in scoped("v2", 5, -1.0)} == {"v2"}
        assert scoped("nope", 5, -1.0) == []
        # no embedding: every crop of the video, in video time, similarity 0, whatever p_min_similarity says
        listed = scoped("v1", None, 0.9)
        assert [row[1] for row in listed] == ["I1", "E1"] and {row[2] for row in listed} == {0.0}, listed
        assert len(conn.execute(
            "SELECT 1 FROM public.search_evidence_items(%s::extensions.vector, 20, -1.0)", (vector_literal(5),)).fetchall()) >= 3

    @test("set_revision_crops refuses a revision that is not the searchable one, and bad input")
    def _():
        first_v3 = one(conn, "SELECT min(id) FROM public.report_revisions WHERE video_id = 'v3'")[0]
        refused(conn, "SELECT public.set_revision_crops('v3', %s, '[]')", (first_v3,), contains="not the searchable revision")
        refused(conn, "SELECT public.set_revision_crops('v1', %s, '[]')", (human["revisionId"],), contains="not the searchable revision")
        refused(conn, "SELECT public.set_revision_crops('v4', NULL, '[]')", contains="not the searchable revision")
        refused(conn, "SELECT public.set_revision_crops('nope', 1, '[]')", contains="Video not found")
        refused(conn, "SELECT public.set_revision_crops('v2', %s, '{}')", (ai2,), contains="crops must be a list")

    @test("saving a newer revision with no official one hides the old rows until the new ones are stored")
    def _():
        newer = save("v2", ai2, report(kind="burglary", severity=3, title="Shop break-in, edited"), [])
        assert searchable("v2") == newer["revisionId"]
        assert searched(5) == [] and crop_count("v2") == 1  # old row stays but is never returned
        refused(conn, "SELECT public.set_revision_crops('v2', %s, '[]')", (ai2,), contains="not the searchable revision")
        set_crops("v2", newer["revisionId"], [crop("entity", "E1", "evidence/v2/u2/E1.jpg", vector(5), item_name="human", description="Burglar")])
        assert searched(5) == [("v2", newer["revisionId"], "E1")] and crop_count("v2") == 1
        assert one(conn, "SELECT count(*) FROM public.evidence_crops WHERE revision_id = %s", (ai2,))[0] == 0

    save_with_crops = lambda video, parent, rows: one(conn, """
        SELECT public.save_human_revision_with_crops(%s, %s, 'Dana', NULL, %s, '[]', 'assault', 4, 2, 9, %s)""",
        (video, parent, json.dumps(report()), json.dumps(rows)))[0]

    @test("save_human_revision_with_crops stores the revision and its crops together when the video has no official revision")
    def _():
        parent = ai_revision("v4", 1, "m1", report(), [])
        rows = [crop("entity", "E1", "evidence/v4/u1/E1.jpg", vector(3), item_name="human", description="Man in a red jacket"),
                crop("asset", "A1", None, vector(4), item_name="bench", description="Bus stop bench")]
        stored = save_with_crops("v4", parent, rows)
        assert stored["revisionNo"] == 2 and stored["parentId"] == parent and stored["crops"] == 1, stored
        assert searchable("v4") == stored["revisionId"] and searched(3) == [("v4", stored["revisionId"], "E1")], searched(3)
        refused(conn, "SELECT public.save_human_revision_with_crops('v4', %s, 'Dana', NULL, %s, '[]', 'assault', 4, 2, 9, '{}')",
                (parent, json.dumps(report())), contains="crops must be a list")

    @test("save_human_revision_with_crops writes no revision when one of its crops cannot be stored")
    def _():
        parent = one(conn, "SELECT max(id) FROM public.report_revisions WHERE video_id = 'v4'")[0]
        before = one(conn, "SELECT count(*) FROM public.report_revisions WHERE video_id = 'v4'")[0]
        searchable_before = searchable("v4")
        bad = [{"item_type": "entity", "item_id": "E9", "image": "evidence/v4/u9/E9.jpg", "embedding": [1.0, 2.0]}]
        refused(conn, """SELECT public.save_human_revision_with_crops('v4', %s, 'Dana', NULL, %s, '[]', 'assault', 4, 2, 9, %s)""",
                (parent, json.dumps(report()), json.dumps(bad)), contains="dimensions")
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE video_id = 'v4'")[0] == before
        assert searchable("v4") == searchable_before, "the searchable revision is unchanged"

    @test("save_human_revision_with_crops leaves an official revision's rows alone")
    def _():
        parent = one(conn, "SELECT max(id) FROM public.report_revisions WHERE video_id = 'v4'")[0]
        assert one(conn, "SELECT public.set_official_revision('v4', %s)", (parent,))[0]["crops"] == 1
        before = crop_count("v4")
        saved = save_with_crops("v4", parent, [crop("entity", "E2", "evidence/v4/u2/E2.jpg", vector(5), item_name="other", description="Ignored")])
        assert saved["crops"] == 0 and crop_count("v4") == before and searchable("v4") == parent, saved
        assert one(conn, "SELECT public.set_official_revision('v4', NULL)")[0]["officialRevisionId"] is None

    @test("marking the newest revision official keeps its rows; clearing it falls back to the newest")
    def _():
        newest = searchable("v2")
        result = one(conn, "SELECT public.set_official_revision('v2', %s)", (newest,))[0]
        assert result["crops"] == 1 and searched(5) == [("v2", newest, "E1")], result
        assert one(conn, "SELECT official_since FROM public.videos WHERE id = 'v2'")[0] is not None
        later = save("v2", newest, report(kind="burglary", severity=3), [])  # official stays; nothing moves
        assert searchable("v2") == newest and searched(5) == [("v2", newest, "E1")]
        refused(conn, "SELECT public.set_revision_crops('v2', %s, '[]')", (later["revisionId"],), contains="not the searchable revision")
        cleared = one(conn, "SELECT public.set_official_revision('v2', NULL)")[0]
        assert cleared == {"videoId": "v2", "officialRevisionId": None, "crops": 0}, cleared  # newest has no rows yet
        assert searchable("v2") == later["revisionId"] and crop_count("v2") == 0 and searched(5) == []
        assert one(conn, "SELECT official_since FROM public.videos WHERE id = 'v2'")[0] is None
        set_crops("v2", later["revisionId"], [crop("asset", "A1", "evidence/v2/u3/A1.jpg", vector(5), item_name="bench", description="Bench")])
        kept = one(conn, "SELECT public.set_official_revision('v2', NULL)")[0]
        assert kept["crops"] == 1 and searched(5) == [("v2", later["revisionId"], "A1")], kept
        assert set_crops("v2", later["revisionId"], [])["crops"] == 0 and crop_count("v2") == 0

    @test("the revisions of other videos are never touched by a crop write")
    def _():
        assert crop_count("v1") == 2 and crop_count("v3") == 0 and crop_count("v4") == 0
    @test("evidence_crops keep the second the box was found at, with its fraction, and a slice and a frame")
    def _():
        conn.execute("INSERT INTO public.videos (id, filepath, source) VALUES ('v11', 'uploads/v11.mp4', 'cam')")
        rev = ai_revision("v11", 1, "m1", report(), [])
        result = set_crops("v11", rev, [
            crop("entity", "E1", "evidence/v11/E1.jpg", vector(7), timestamp_seconds=15.333, slice_start_seconds=15.333,
                 slice_end_seconds=18.8, frame="evidence/v11/E1-frame.jpg", item_name="human", description="Man"),
            crop("asset", "A1", "evidence/v11/A1.jpg", vector(8), timestamp_seconds=2.27, slice_start_seconds=-1,
                 slice_end_seconds=5.27, item_name="shelf", description="Shelf"),
            crop("instrument", "I1", "evidence/v11/I1.jpg", vector(9), timestamp_seconds=4, item_name="bottle", description="Old crop list"),
        ])
        assert result["crops"] == 3, result
        rows = conn.execute("""SELECT item_id, timestamp_seconds, slice_start_seconds, slice_end_seconds, frame
            FROM public.evidence_crops WHERE revision_id = %s ORDER BY item_id""", (rev,)).fetchall()
        assert rows == [
            ("A1", Decimal("2.270"), Decimal("0.000"), Decimal("5.270"), None),
            ("E1", Decimal("15.333"), Decimal("15.333"), Decimal("18.800"), "evidence/v11/E1-frame.jpg"),
            ("I1", Decimal("4.000"), None, None, None),
        ], rows
        hits = conn.execute("""SELECT item_id, timestamp_seconds, slice_start_seconds, slice_end_seconds, frame
            FROM public.search_evidence_items(%s::extensions.vector, 5, 0.5, p_video_id => 'v11')""", (vector_literal(7),)).fetchall()
        assert hits == [("E1", Decimal("15.333"), Decimal("15.333"), Decimal("18.800"), "evidence/v11/E1-frame.jpg")], hits
        conn.execute("DELETE FROM public.videos WHERE id = 'v11'")

    @test("evidence_slice: box second wins over the item's second; a track gives first to last seen, else 3 s either side")
    def _():
        slice_of = lambda entry: one(conn, "SELECT box_second, slice_start, slice_end FROM public.evidence_slice(%s::jsonb)",
                                     (json.dumps(entry),))
        D = Decimal
        # the audit's cases: a fractional box second beside a different whole-second item time
        assert slice_of({"box_seconds": 15.33, "timestamp_seconds": 18}) == (D("15.33"), D("12.33"), D("18.33"))
        assert slice_of({"box_seconds": 2.27, "timestamp_seconds": 22}) == (D("2.27"), D("0"), D("5.27"))
        assert slice_of({"box_seconds": 10.67, "timestamp_seconds": 0}) == (D("10.67"), D("7.67"), D("13.67"))
        track = {"box_seconds": 15.33, "track": "evidence/x/E1-track.json",
                 "track_first_seen_seconds": 15.33, "track_last_seen_seconds": 18.8}
        assert slice_of(track) == (D("15.33"), D("15.33"), D("18.8"))
        # a track key without a usable window, or a window without a key, is not a track
        assert slice_of({**track, "track_last_seen_seconds": 10}) == (D("15.33"), D("12.33"), D("18.33"))
        assert slice_of({**track, "track": None}) == (D("15.33"), D("12.33"), D("18.33"))
        assert slice_of({"timestamp_seconds": 5}) == (D("5"), D("2"), D("8"))
        assert slice_of({}) == (D("0"), D("0"), D("3"))

    @test("backfill: a row with a wrong second and no slice is rewritten from its revision's evidence, embedding kept")
    def _():
        conn.execute("INSERT INTO public.videos (id, filepath, source) VALUES ('v12', 'uploads/v12.mp4', 'cam')")
        evidence = [
            {"item_type": "entity", "item_id": "E1", "image": "evidence/v12/E1.jpg", "box_seconds": 15.33, "timestamp_seconds": 18,
             "frame": "evidence/v12/E1-frame.jpg", "track": "evidence/v12/E1-track.json",
             "track_first_seen_seconds": 15.33, "track_last_seen_seconds": 18.8},
            {"item_type": "asset", "item_id": "A1", "image": "evidence/v12/A1.jpg", "box_seconds": 2.27, "timestamp_seconds": 22},
        ]
        rev = ai_revision("v12", 1, "m1", report(), evidence)
        for item_type, item_id, wrong in (("entity", "E1", 18), ("asset", "A1", 22)):
            conn.execute("""INSERT INTO public.evidence_crops (revision_id, item_type, item_id, item_name, description,
                                timestamp_seconds, bounding_box, image, embedding)
                            VALUES (%s, %s, %s, 'n', 'd', %s, '{1,2,3,4}', %s, %s::extensions.vector)""",
                         (rev, item_type, item_id, wrong, f"evidence/v12/{item_id}.jpg", vector_literal(11)))
        before = one(conn, "SELECT embedding::TEXT FROM public.evidence_crops WHERE revision_id = %s AND item_id = 'E1'", (rev,))[0]
        conn.execute("RESET ROLE")
        with conn.transaction():
            conn.execute(next(m for m in MIGRATIONS if m.name.startswith("20261105090000")).read_text())
        conn.execute("SET ROLE service_role")
        rows = conn.execute("""SELECT item_id, timestamp_seconds, slice_start_seconds, slice_end_seconds, frame, embedding::TEXT
            FROM public.evidence_crops WHERE revision_id = %s ORDER BY item_id""", (rev,)).fetchall()
        assert [r[:5] for r in rows] == [
            ("A1", Decimal("2.270"), Decimal("0.000"), Decimal("5.270"), None),
            ("E1", Decimal("15.330"), Decimal("15.330"), Decimal("18.800"), "evidence/v12/E1-frame.jpg"),
        ], rows
        assert rows[1][5] == before, "the embedding is not re-written"
        conn.execute("DELETE FROM public.videos WHERE id = 'v12'")

    @test("list_revisions_missing_crops: a searchable revision with images and no crop rows, nothing else")
    def _():
        missing = lambda video=None: conn.execute("SELECT video_id, revision_id FROM public.list_revisions_missing_crops(%s)",
                                                  (video,)).fetchall()
        image = {"item_type": "entity", "item_id": "E1", "image": "evidence/v13/E1.jpg"}
        conn.execute("INSERT INTO public.videos (id, filepath, source) VALUES ('v13', 'uploads/v13.mp4', 'cam'), ('v14', 'uploads/v14.mp4', 'cam')")
        old = ai_revision("v13", 1, "m1", report(), [image])
        assert missing("v13") == [("v13", old)], "newest revision has images and no rows"
        set_crops("v13", old, [crop("entity", "E1", "evidence/v13/E1.jpg", vector(12), item_name="n", description="d")])
        assert missing("v13") == []
        newer = ai_revision("v13", 2, "m1", report(), [image])
        assert missing("v13") == [("v13", newer)], "a newer revision takes over search with no rows"
        ai_revision("v14", 1, "m1", report(), [{"item_type": "asset", "item_id": "A1", "image": None}])
        assert missing("v14") == [], "no image-bearing evidence, nothing to store"
        assert ("v13", newer) in missing()
        refused(conn, "UPDATE public.report_revisions SET note = 'x' WHERE id = %s", (newer,), contains="append-only")
        conn.execute("DELETE FROM public.videos WHERE id IN ('v13', 'v14')")

    @test("apply_r2_rename points a video, its evidence and its crops at renamed keys and nothing else")
    def _():
        conn.execute("INSERT INTO public.videos (id, filepath, source) VALUES ('v10', 'uploads/cam/0123.mp4', 'cam')")
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
        conn.execute("INSERT INTO public.videos (id) VALUES ('v8'), ('v9')")
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

    # One searchable version per incident (20261106090000_one_searchable_version.sql).
    summary_hits = lambda index, floor=0.5: conn.execute(
        "SELECT video_id, revision_id, similarity_score FROM public.search_report_revisions(%s::extensions.vector, 20, %s) ORDER BY video_id",
        (vector_literal(index), floor)).fetchall()
    embed_rev = lambda video, revision, index: one(
        conn, "SELECT public.set_revision_embedding(%s, %s, %s::extensions.vector)", (video, revision, vector_literal(index)))[0]

    @test("search_report_revisions returns only the searchable version, so a video never has two hits")
    def _():
        conn.execute("INSERT INTO public.videos (id) VALUES ('vs')")
        old = one(conn, """INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds, embedding)
            VALUES ('vs', 1, 'ai', 'm1', %s, '[]', 'assault', 4, 2, 9, %s::extensions.vector) RETURNING id""",
            (json.dumps(report(title="Old")), vector_literal(20)))[0]
        newest = one(conn, """INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, parent_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds, embedding, created_by)
            VALUES ('vs', 2, 'human', 'm1', %s, %s, '[]', 'assault', 4, 2, 9, %s::extensions.vector, 'Dana') RETURNING id""",
            (old, json.dumps(report(title="Newest")), vector_literal(20)))[0]
        assert summary_hits(20) == [("vs", newest, 1.0)], summary_hits(20)  # the older twin vector is not a second hit
        assert searchable("vs") == newest
        # Marking the older one official moves the single hit to it; clearing moves it back to the newest.
        conn.execute("SELECT public.set_official_revision('vs', %s, '[]')", (old,))
        assert summary_hits(20) == [("vs", old, 1.0)], summary_hits(20)
        conn.execute("SELECT public.set_official_revision('vs', NULL)")
        assert summary_hits(20) == [("vs", newest, 1.0)], summary_hits(20)
        assert summary_hits(20, 1.1) == [], "the minimum similarity still applies"

    @test("marking official, clearing it and saving a new version each leave one searchable version for both searches")
    def _():
        conn.execute("INSERT INTO public.videos (id) VALUES ('vt')")
        first = ai_revision("vt", 1, "m1", report(title="First"), [])
        embed_rev("vt", first, 21)
        set_crops("vt", first, [crop("entity", "E1", "evidence/vt/u1/E1.jpg", vector(21), item_name="human", description="One")])
        second = save("vt", first, report(title="Second"), [])["revisionId"]
        assert searchable("vt") == second
        assert summary_hits(21) == [] and searched(21) == [], "nothing of the older version is found once a newer one exists"
        assert embed_rev("vt", second, 22) is True
        set_crops("vt", second, [crop("entity", "E1", "evidence/vt/u2/E1.jpg", vector(22), item_name="human", description="Two")])
        assert [h[:2] for h in summary_hits(22)] == [("vt", second)] and searched(22) == [("vt", second, "E1")]
        conn.execute("SELECT public.set_official_revision('vt', %s, %s)", (first, json.dumps([crop("entity", "E1", "evidence/vt/u1/E1.jpg", vector(21), item_name="human", description="One")])))
        assert [h[:2] for h in summary_hits(21)] == [("vt", first)] and searched(21) == [("vt", first, "E1")]
        assert summary_hits(22) == [] and searched(22) == []
        conn.execute("SELECT public.set_official_revision('vt', NULL)")
        assert searchable("vt") == second and [h[:2] for h in summary_hits(22)] == [("vt", second)]
        assert summary_hits(21) == [], "clearing official hides the older version again"

    @test("save_human_revision stores the summary vector it is given, and still saves without one")
    def _():
        conn.execute("INSERT INTO public.videos (id) VALUES ('vu')")
        parent = ai_revision("vu", 1, "m1", report(), [])
        args = ("vu", parent, "Dana", None, json.dumps(report(title="Edited")), "[]", "assault", 4, 2, 9)
        saved = one(conn, "SELECT public.save_human_revision(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector)",
                    args + (vector_literal(23),))[0]
        assert [h[:2] for h in summary_hits(23)] == [("vu", saved["revisionId"])]
        bare = one(conn, "SELECT public.save_human_revision(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", args)[0]
        assert one(conn, "SELECT embedding IS NULL FROM public.report_revisions WHERE id = %s", (bare["revisionId"],))[0]
        withcrops = one(conn, """SELECT public.save_human_revision_with_crops(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector)""",
                        args + ("[]", vector_literal(24)))[0]
        assert [h[:2] for h in summary_hits(24)] == [("vu", withcrops["revisionId"])]
        refused(conn, "SELECT public.save_human_revision(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '[1,2]'::extensions.vector)", args, contains="dimensions")

    @test("set_revision_embedding fills only a missing vector on the searchable version, and the guard allows nothing else")
    def _():
        parent = searchable("vu")
        searchable_id = save("vu", parent, report(title="Edited"), [])["revisionId"]  # saved without a vector
        assert searchable("vu") == searchable_id
        assert one(conn, "SELECT embedding IS NULL FROM public.report_revisions WHERE id = %s", (searchable_id,))[0]
        listed = conn.execute("SELECT video_id, revision_id, title FROM public.list_revisions_missing_embeddings('vu')").fetchall()
        assert conn.execute("SELECT incident_type FROM public.list_revisions_missing_embeddings('vu')").fetchall() is not None
        assert listed == [("vu", searchable_id, "Edited")], listed
        refused(conn, "SELECT public.set_revision_embedding('vu', %s, %s::extensions.vector)",
                (one(conn, "SELECT min(id) FROM public.report_revisions WHERE video_id = 'vu'")[0], vector_literal(25)),
                contains="not the searchable revision")
        refused(conn, "SELECT public.set_revision_embedding('vu', %s, NULL)", (searchable_id,), contains="embedding is required")
        assert one(conn, "SELECT public.set_revision_embedding('vu', %s, %s::extensions.vector)", (searchable_id, vector_literal(25)))[0] is True
        assert [h[:2] for h in summary_hits(25)] == [("vu", searchable_id)]
        assert conn.execute("SELECT * FROM public.list_revisions_missing_embeddings('vu')").fetchall() == []
        assert one(conn, "SELECT public.set_revision_embedding('vu', %s, %s::extensions.vector)", (searchable_id, vector_literal(26)))[0] is False
        assert summary_hits(26) == [], "a stored vector is never replaced"
        assert one(conn, "SELECT current_setting('app.revision_embedding', true)")[0] in (None, "", "off")
        for sql in ("UPDATE public.report_revisions SET embedding = NULL WHERE id = %s",
                    "UPDATE public.report_revisions SET embedding = embedding WHERE id = %s",
                    "UPDATE public.report_revisions SET note = 'x' WHERE id = %s"):
            refused(conn, sql, (searchable_id,), contains="append-only")
        # Even with the flag on, a change to another column, or a replacement of a stored vector, is refused.
        with conn.transaction(force_rollback=True):
            conn.execute("SELECT set_config('app.revision_embedding', 'on', true)")
            for sql in ("UPDATE public.report_revisions SET note = 'x' WHERE id = %s",
                        "UPDATE public.report_revisions SET embedding = NULL WHERE id = %s"):
                try:
                    with conn.transaction():
                        conn.execute(sql, (searchable_id,))
                except errors.Error as exc:
                    assert "append-only" in str(exc)
                else:
                    raise AssertionError(sql)

    @test("repair_revision_crops stores crops once, never over existing rows, and not for a version that is no longer searchable")
    def _():
        conn.execute("INSERT INTO public.videos (id) VALUES ('vw')")
        base = ai_revision("vw", 1, "m1", report(), EVIDENCE)
        rows = [crop("entity", "E1", "evidence/vw/u1/E1.jpg", vector(27), item_name="human", description="One")]
        newer = ai_revision("vw", 2, "m1", report(), EVIDENCE)
        assert one(conn, "SELECT public.repair_revision_crops('vw', %s, %s)", (base, json.dumps(rows)))[0] is None, "not searchable"
        assert crop_count("vw") == 0
        assert one(conn, "SELECT public.repair_revision_crops('vw', %s, %s)", (newer, json.dumps(rows)))[0] == 1
        other = [crop("entity", "E1", "evidence/vw/u9/E1.jpg", vector(28), item_name="human", description="Other")]
        assert one(conn, "SELECT public.repair_revision_crops('vw', %s, %s)", (newer, json.dumps(other)))[0] is None
        assert one(conn, "SELECT image FROM public.evidence_crops WHERE revision_id = %s", (newer,))[0] == "evidence/vw/u1/E1.jpg"
        assert one(conn, "SELECT public.repair_revision_crops('nope', 1, '[]')")[0] is None

    @test("refresh_revision_embedding replaces a stored vector on the searchable version only, and the guard allows nothing else")
    def _():
        searchable_id = searchable("vu")
        old_id = one(conn, "SELECT min(id) FROM public.report_revisions WHERE video_id = 'vu'")[0]
        assert summary_hits(25) and summary_hits(25)[0][1] == searchable_id  # holds the vector set by the test above
        refused(conn, "SELECT public.refresh_revision_embedding('vu', %s, %s::extensions.vector)", (old_id, vector_literal(30)),
                contains="not the searchable revision")
        refused(conn, "SELECT public.refresh_revision_embedding('vu', %s, NULL)", (searchable_id,), contains="embedding is required")
        refused(conn, "SELECT public.refresh_revision_embedding('nope', 1, %s::extensions.vector)", (vector_literal(30),),
                contains="Video not found")
        assert one(conn, "SELECT public.refresh_revision_embedding('vu', %s, %s::extensions.vector)", (searchable_id, vector_literal(30)))[0] is True
        assert [h[:2] for h in summary_hits(30)] == [("vu", searchable_id)], "the new vector is the one searched"
        assert summary_hits(25) == [], "the old vector is gone"
        assert one(conn, "SELECT current_setting('app.revision_embedding_refresh', true)")[0] in (None, "", "off")
        for sql in ("UPDATE public.report_revisions SET embedding = %s::extensions.vector WHERE id = %s",):
            refused(conn, sql, (vector_literal(31), searchable_id), contains="append-only")
        with conn.transaction(force_rollback=True):
            conn.execute("SELECT set_config('app.revision_embedding_refresh', 'on', true)")
            for sql in ("UPDATE public.report_revisions SET note = 'x' WHERE id = %s",
                        "UPDATE public.report_revisions SET embedding = NULL WHERE id = %s"):
                try:
                    with conn.transaction():
                        conn.execute(sql, (searchable_id,))
                except errors.Error as exc:
                    assert "append-only" in str(exc), exc
                else:
                    raise AssertionError(f"allowed with the refresh flag on: {sql}")

    @test("security: the 20261106 functions are for the service role only")
    def _():
        conn.execute("RESET ROLE")
        for sig in ("public.set_revision_embedding(character varying, bigint, extensions.vector)",
                    "public.list_revisions_missing_embeddings(character varying)",
                    "public.refresh_revision_embedding(character varying, bigint, extensions.vector)",
                    "public.repair_revision_crops(character varying, bigint, jsonb)"):
            for role in ("anon", "authenticated"):
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))[0], (role, sig)
            assert one(conn, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,))[0], sig
        conn.execute("SET ROLE service_role")
        conn.execute("DELETE FROM public.videos WHERE id IN ('vs', 'vt', 'vu', 'vw')")

    # Background analysis jobs (20261031120000_analysis_jobs.sql).
    def enqueue(name: str) -> int:
        return one(conn, "INSERT INTO public.analysis_jobs (file_path, filename, model) VALUES (%s, %s, 'model-a') RETURNING id",
                   (f"uploads/{name}", name))[0]

    def claim(stale_seconds: int = 180):
        row = conn.execute("SELECT id, status, attempts, started_at IS NOT NULL, heartbeat_at IS NOT NULL "
                           "FROM public.claim_analysis_job(%s)", (stale_seconds,)).fetchone()
        return row

    job_status = lambda job: one(conn, "SELECT status, attempts, error FROM public.analysis_jobs WHERE id = %s", (job,))
    age = lambda job, seconds: conn.execute(
        "UPDATE public.analysis_jobs SET heartbeat_at = heartbeat_at - make_interval(secs => %s) WHERE id = %s", (seconds, job))
    finish = lambda job, attempt, status, error=None, video=None, revision=None: conn.execute(
        "SELECT id, status, error, video_id, revision_id FROM public.finish_analysis_job(%s, %s, %s, %s, %s, %s)",
        (job, attempt, status, error, video, revision)).fetchall()

    @test("analysis jobs: a new job is queued and claims run oldest first, one at a time")
    def _():
        first, second = enqueue("a.mp4"), enqueue("b.mp4")
        assert job_status(first) == ("queued", 0, None)
        assert claim() == (first, "running", 1, True, True)
        assert claim() == (second, "running", 1, True, True)
        assert claim() is None, "nothing left to claim"
        assert finish(first, 1, "done", video="v2", revision=ai2) == [(first, "done", None, "v2", ai2)]
        assert finish(second, 1, "failed", error="  ") == [(second, "failed", "The analysis failed", None, None)]

    @test("analysis jobs: only the claim that is still running can heartbeat or finish")
    def _():
        job = enqueue("c.mp4")
        assert claim()[0] == job
        assert one(conn, "SELECT public.touch_analysis_job(%s, 1)", (job,))[0] is True
        assert one(conn, "SELECT public.touch_analysis_job(%s, 2)", (job,))[0] is False, "another claim's attempt"
        assert finish(job, 2, "done", video="v2", revision=ai2) == []
        refused(conn, "SELECT * FROM public.finish_analysis_job(%s, 1, 'done')", (job,), contains="needs its video")
        refused(conn, "SELECT * FROM public.finish_analysis_job(%s, 1, 'running')", (job,), contains="done or failed")
        assert finish(job, 1, "failed", error="Unsupported model") == [(job, "failed", "Unsupported model", None, None)]
        assert one(conn, "SELECT public.touch_analysis_job(%s, 1)", (job,))[0] is False, "a finished job takes no heartbeat"
        assert finish(job, 1, "done", video="v2", revision=ai2) == [], "a finished job is not finished again"

    @test("analysis jobs: a stale running job is queued again once, then failed")
    def _():
        job = enqueue("d.mp4")
        assert claim()[0] == job
        age(job, 120)
        assert claim() is None and job_status(job)[0] == "running", "a fresh enough heartbeat is left alone"
        age(job, 120)
        assert claim() == (job, "running", 2, True, True), "first stale run: back to the queue and claimed again"
        assert one(conn, "SELECT public.touch_analysis_job(%s, 1)", (job,))[0] is False, "the old runner lost its claim"
        age(job, 600)
        assert claim() is None
        status, attempts, error = job_status(job)
        assert (status, attempts) == ("failed", 2) and "stopped twice" in error, (status, attempts, error)
        assert one(conn, "SELECT finished_at IS NOT NULL FROM public.analysis_jobs WHERE id = %s", (job,))[0]
        refused(conn, "SELECT * FROM public.claim_analysis_job(0)", contains="at least 1")

    @test("analysis jobs: retry requeues a failed or cancelled job; cancel takes only a queued one")
    def _():
        failed = one(conn, "SELECT id FROM public.analysis_jobs WHERE filename = 'd.mp4'")[0]
        retried = conn.execute("SELECT status, attempts, error, started_at, finished_at FROM public.retry_analysis_job(%s)",
                               (failed,)).fetchall()
        assert retried == [("queued", 0, None, None, None)], retried
        assert conn.execute("SELECT id FROM public.retry_analysis_job(%s)", (failed,)).fetchall() == [], "a queued job is not retried"
        cancelled = conn.execute("SELECT status FROM public.cancel_analysis_job(%s)", (failed,)).fetchall()
        assert cancelled == [("cancelled",)] and claim() is None, "a cancelled job is never claimed"
        assert conn.execute("SELECT status FROM public.retry_analysis_job(%s)", (failed,)).fetchall() == [("queued",)]
        assert claim()[0] == failed
        assert conn.execute("SELECT id FROM public.cancel_analysis_job(%s)", (failed,)).fetchall() == [], "a running job is not cancelled"
        done = one(conn, "SELECT id FROM public.analysis_jobs WHERE status = 'done'")[0]
        assert conn.execute("SELECT id FROM public.retry_analysis_job(%s)", (done,)).fetchall() == [], "a done job is not retried"
        assert finish(failed, 1, "failed", error="x")[0][1] == "failed"

    @test("analysis jobs: two loops never claim the same job")
    def _():
        job = enqueue("e.mp4")
        other = psycopg.connect(server.get_uri(), autocommit=True)
        try:
            other.execute("SET ROLE service_role")
            with conn.transaction():
                assert claim()[0] == job
                # the first claim is not committed yet: the second loop skips the locked row
                assert other.execute("SELECT id FROM public.claim_analysis_job(180)").fetchall() == []
            assert other.execute("SELECT id FROM public.claim_analysis_job(180)").fetchall() == []
        finally:
            other.close()
        assert finish(job, 1, "failed", error="x")[0][1] == "failed"
        refused(conn, "INSERT INTO public.analysis_jobs (file_path, filename, status) VALUES ('k', 'k', 'paused')",
                contains="analysis_jobs_status_check")

    @test("security: analysis jobs are for the service role only")
    def _():
        conn.execute("RESET ROLE")
        for role in ("anon", "authenticated"):
            assert not one(conn, "SELECT has_table_privilege(%s, 'public.analysis_jobs', 'SELECT')", (role,))[0], role
            for sig in ("public.claim_analysis_job(integer)", "public.touch_analysis_job(bigint, integer)",
                        "public.finish_analysis_job(bigint, integer, text, text, character varying, bigint)",
                        "public.retry_analysis_job(bigint)", "public.cancel_analysis_job(bigint)"):
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))[0], (role, sig)
        assert one(conn, "SELECT has_function_privilege('service_role', 'public.claim_analysis_job(integer)', 'EXECUTE')")[0]
        conn.execute("SET ROLE service_role")

    # Privacy blur removal (20261102090000_drop_blur_faces.sql).
    @test("privacy blur removal: the columns and the extra claim are gone, and a pending re-analysis job is cancelled")
    def _():
        def blur_columns():
            return [r[0] for r in conn.execute(
                "SELECT table_name || '.' || column_name FROM information_schema.columns WHERE table_schema = 'public' "
                "AND column_name IN ('blur_faces', 'reanalyse_video_id') ORDER BY 1").fetchall()]
        assert blur_columns() == [], blur_columns()
        assert "claim_queued_analysis_job" not in " ".join(functions)
        # The live shape before the migration: the three columns and a re-analysis job that has not finished.
        # The migration runs as the schema owner, like the Supabase editor does.
        conn.execute("RESET ROLE")
        conn.execute("INSERT INTO public.videos (id, filepath) VALUES ('vb', 'uploads/vb.mp4')")
        conn.execute("ALTER TABLE public.videos ADD COLUMN blur_faces BOOLEAN NOT NULL DEFAULT false")
        conn.execute("ALTER TABLE public.analysis_jobs ADD COLUMN blur_faces BOOLEAN NOT NULL DEFAULT false, "
                     "ADD COLUMN reanalyse_video_id VARCHAR(20) REFERENCES public.videos (id) ON DELETE CASCADE")
        job = one(conn, "INSERT INTO public.analysis_jobs (file_path, filename, reanalyse_video_id, blur_faces) "
                        "VALUES ('uploads/vb.mp4', 'vb.mp4', 'vb', true) RETURNING id")[0]
        upload = enqueue("upload.mp4")
        migration = (HERE.parent / "migrations" / "20261102090000_drop_blur_faces.sql").read_text()
        for _ in range(2):  # the second run changes nothing
            with conn.transaction():
                conn.execute(migration)
            assert blur_columns() == [], blur_columns()
        conn.execute("SET ROLE service_role")
        assert job_status(job)[0] == "cancelled", "a queued re-analysis job must not run as an upload of a new video"
        assert conn.execute("SELECT id FROM public.claim_analysis_job(180)").fetchone() == (upload,)
        refused(conn, "SELECT * FROM public.claim_analysis_job(0)", contains="at least 1")
        assert finish(upload, 1, "failed", error="x")[0][1] == "failed"
        conn.execute("DELETE FROM public.analysis_jobs WHERE id = %s", (job,))
        conn.execute("DELETE FROM public.videos WHERE id = 'vb'")
        conn.execute("RESET ROLE")
        for role in ("anon", "authenticated"):
            assert not one(conn, "SELECT has_function_privilege(%s, 'public.claim_analysis_job(integer)', 'EXECUTE')", (role,))[0]
        assert one(conn, "SELECT has_function_privilege('service_role', 'public.claim_analysis_job(integer)', 'EXECUTE')")[0]
        conn.execute("SET ROLE service_role")

    @test("content hash: one video per file content, one active job per file content, failed jobs release it")
    def _():
        a, b = "a" * 64, "b" * 64
        conn.execute("INSERT INTO public.videos (id, filepath, content_sha256) VALUES ('hv1', 'uploads/h1.mp4', %s)", (a,))
        refused(conn, "INSERT INTO public.videos (id, filepath, content_sha256) VALUES ('hv2', 'uploads/h1-2.mp4', %s)", (a,),
                kind=errors.UniqueViolation, contains="videos_content_sha256_key")
        refused(conn, "INSERT INTO public.videos (id, filepath, content_sha256) VALUES ('hv3', 'uploads/h3.mp4', 'NOT-A-HASH')",
                contains="videos_content_sha256_check")
        # Videos without a hash (older rows before the backfill, seeded clips) are never constrained.
        conn.execute("INSERT INTO public.videos (id, filepath) VALUES ('hn1', 'uploads/n1.mp4'), ('hn2', 'uploads/n2.mp4')")
        add = "INSERT INTO public.analysis_jobs (file_path, filename, content_sha256) VALUES (%s, %s, %s) RETURNING id"
        first = one(conn, add, ("uploads/j.mp4", "j.mp4", b))[0]
        refused(conn, add, ("uploads/j-2.mp4", "j-2.mp4", b), kind=errors.UniqueViolation,
                contains="analysis_jobs_active_content_sha256_key")
        conn.execute("UPDATE public.analysis_jobs SET status = 'failed' WHERE id = %s", (first,))
        second = one(conn, add, ("uploads/j-3.mp4", "j-3.mp4", b))[0]
        conn.execute("DELETE FROM public.analysis_jobs WHERE id IN (%s, %s)", (first, second))
        conn.execute("DELETE FROM public.videos WHERE id IN ('hv1', 'hn1', 'hn2')")

    @test("deleting a video removes its revisions, crops and query results")
    def _():
        conn.execute("INSERT INTO public.queries (id, query_text) VALUES ('q1', 'man')")
        conn.execute("""INSERT INTO public.query_results (id, query_id, revision_id, item_type, item_id, rank, similarity_score, critic_verdict)
                        VALUES ('r1', 'q1', %s, 'entity', 'E1', 1, 0.9, 'confirmed')""", (ai1,))
        linked = one(conn, "INSERT INTO public.analysis_jobs (file_path, filename, status, video_id, revision_id) "
                           "VALUES ('uploads/v1.mp4', 'v1.mp4', 'done', 'v1', %s) RETURNING id", (ai1,))[0]
        conn.execute("DELETE FROM public.videos WHERE id = 'v1'")
        assert one(conn, "SELECT status, video_id, revision_id FROM public.analysis_jobs WHERE id = %s", (linked,)) == ("done", None, None)
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE video_id = 'v1'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.evidence_crops")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.query_results")[0] == 0

    conn.execute("RESET ROLE")
    conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
