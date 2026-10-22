# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests of the finals schema on a throwaway Postgres (no Supabase, no network).

    cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py

Applies every file in supabase/migrations/ in order (the finals baseline, then any later finals
migration). pgserver ships Postgres 16 with pgvector. supabase_stub.sql adds the API roles and Supabase's
default grants, so the lockdown is tested against what a new project really starts with.
Writes go through SET ROLE service_role, the role PostgREST uses with the service key.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg
from psycopg import errors

HERE = Path(__file__).resolve().parent
MIGRATIONS = sorted((HERE.parent / "migrations").glob("*.sql"))
COPY = HERE.parent / "copy"
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


def edit_payload(description="Edited.", entities=None, instruments=None, assets=None, start=1, end=9):
    return json.dumps({
        "incident": {"type": "assault", "start_timestamp": start, "end_timestamp": end, "description": description, "severity_level": 4},
        "entities": entities if entities is not None else [{"entity_id": "E1", "source_id": "E1", "type": "human", "description": "Attacker"}],
        "instruments": instruments if instruments is not None else [],
        "assets": assets if assets is not None else [{"asset_id": "A1", "source_id": "A1", "name": "car", "description": "parked"}],
    })


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

    @test(f"schema: 20 tables, 4 views, {len(functions)} functions, no legacy or superseded objects")
    def _():
        kinds = dict(conn.execute("SELECT relkind::TEXT, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                  "WHERE n.nspname = 'public' AND relkind IN ('r','v') GROUP BY 1").fetchall())
        assert kinds == {"r": 20, "v": 4}, kinds
        names = " ".join(tables + functions)
        for gone in ("incident_reports", "incident_entities", "apply_incident_report_patch", "replace_incident_evidence",
                     "asset_matches", "entity_matches", "instrument_matches", "notifications"):
            assert gone not in names, gone
        assert one(conn, "SELECT extnamespace::regnamespace::TEXT FROM pg_extension WHERE extname = 'vector'")[0] == "extensions"

    @test("security: anon and authenticated cannot read any table or view, or run any function")
    def _():
        for role in ("anon", "authenticated"):
            conn.execute(f"SET ROLE {role}")
            for table in tables:
                refused(conn, f"SELECT 1 FROM {table} LIMIT 1", kind=errors.InsufficientPrivilege)
            for fn in functions:
                assert not one(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))[0], (role, fn)
            # Real calls too (a strict function called with NULLs is folded away before any check).
            refused(conn, "SELECT public.insert_incident('v', 'r', 'assault', '0', '1', 1, 'd', 3, 0.5)", kind=errors.InsufficientPrivilege)
            refused(conn, "SELECT public.list_incident_report_summaries()", kind=errors.InsufficientPrivilege)
            refused(conn, "SELECT public.set_review_status('v', 'r', 'verified', 'x')", kind=errors.InsufficientPrivilege)
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
    vec = lambda x: "[" + ",".join(str(x if i == 0 else 0.001) for i in range(1024)) + "]"

    # Run r1: a contract-style AI report with two entities, one instrument, one asset.
    conn.execute("INSERT INTO public.videos (id, filepath) VALUES ('v1', 'uploads/s/v1.mp4'), ('v2', 'uploads/s/v2.mp4'), ('v3', 'uploads/s/v3.mp4')")
    conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES ('r1', 'm'), ('r2', 'm'), ('r3', 'm')")
    conn.execute("SELECT public.insert_incident('v1', 'r1', 'assault', '1', '9', 8, 'AI said this.', 3, 0.8)")
    conn.execute("""INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description) VALUES
        ('v1', 'E1', 'r1', 'human', 'Attacker'), ('v1', 'E2', 'r1', 'human', 'Bystander')""")
    conn.execute("INSERT INTO public.instruments VALUES ('v1', 'I1', 'r1', 'E1', 'bat', 'swung', 4, NULL)")
    conn.execute("INSERT INTO public.assets (incident_id, asset_id, model_run_id, name, description) VALUES ('v1', 'A1', 'r1', 'car', 'parked')")
    conn.execute("INSERT INTO public.reports (id, incident_id, model_run_id) VALUES ('rep1', 'v1', 'r1')")
    for item_type, item_id, x in (("entity", "E1", 1.0), ("entity", "E2", 0.9), ("asset", "A1", 0.5), ("instrument", "I1", 0.7)):
        conn.execute("""INSERT INTO public.evidence_crops (incident_id, model_run_id, item_type, item_id, item_name, description,
            timestamp_seconds, bounding_box, image, embedding) VALUES ('v1', 'r1', %s, %s, 'n', 'ai text', 2, '{0,0,10,10}', 'k', %s)""",
            (item_type, item_id, vec(x)))
    conn.execute("SELECT public.select_official_report('v1', 'r1', 'rev')")

    def ai_rows():
        return conn.execute("SELECT i.description, (SELECT count(*) FROM public.entities WHERE model_run_id = 'r1') FROM public.incidents i WHERE model_run_id = 'r1'").fetchone()

    @test("effective views show the AI report while there is no reviewer version")
    def _():
        assert one(conn, "SELECT description, source FROM public.effective_incidents WHERE model_run_id = 'r1'") == ("AI said this.", "ai")
        assert one(conn, "SELECT count(*) FROM public.effective_entities WHERE model_run_id = 'r1' AND source = 'ai'")[0] == 2

    @test("edit through the old RPC name writes only the reviewer version and returns the old keys")
    def _():
        result = one(conn, "SELECT public.apply_structured_report_edit('v1', 'r1', %s, ' Kai ')", (edit_payload(
            instruments=[{"instrument_id": "I1", "source_id": "I1", "entity_id": "E1", "name": "bat", "description": "swung hard", "threat_level": 5}]),))[0]
        assert {"incidentId", "modelRunId", "editedBy", "editedAt", "duration"} <= set(result), result
        assert result["editedBy"] == "Kai" and result["duration"] == 8 and result["revision"] == 1
        assert ai_rows() == ("AI said this.", 2), ai_rows()
        assert one(conn, "SELECT description, source FROM public.effective_incidents WHERE model_run_id = 'r1'") == ("Edited.", "human")
        assert conn.execute("SELECT entity_id, source_entity_id FROM public.human_report_entities ORDER BY 1").fetchall() == [("E1", "E1")]
        assert one(conn, "SELECT edited_by FROM public.review_status WHERE model_run_id = 'r1'")[0] == "Kai"

    def search(incident_id):
        return conn.execute("SELECT item_type, item_id, item_name, item_description, incident_description, threat_level "
                            "FROM public.search_evidence_items(%s::extensions.vector, 100, -1) WHERE incident_id = %s ORDER BY 1, 2",
                            (vec(1.0), incident_id)).fetchall()

    @test("search hides the crop of an item the reviewer removed and shows the reviewer's text and names")
    def _():
        rows = search("v1")
        assert ("entity", "E2") not in [(r[0], r[1]) for r in rows], rows
        assert ("entity", "E1", "human", "Attacker", "Edited.", None) in rows, rows  # an entity's name is its (reviewer) type
        assert ("instrument", "I1", "bat", "swung hard", "Edited.", 5) in rows, rows

    @test("library and dashboard read the reviewer version")
    def _():
        lib = one(conn, "SELECT public.list_incident_report_summaries(p_page_size => 10)")[0]
        assert lib["totalItems"] == 1 and lib["reports"][0]["description"] == "Edited." and lib["reports"][0]["severity"] == 4, lib
        dash = one(conn, "SELECT public.get_incident_dashboard()")[0]
        assert dash["total"] == 1 and dash["severity"]["high"] == 1, dash["severity"]
        assert {"label": "car", "count": 1} in dash["topAssets"], dash["topAssets"]

    @test("verify keeps the reviewer version and never touches the edit stamp; a later edit reopens review")
    def _():
        r = one(conn, "SELECT public.set_review_status('v1', 'r1', 'verified', 'Lead')")[0]
        assert r["changed"] and not r["humanVersionCreated"] and r["verifiedBy"] == "Lead", r
        assert one(conn, "SELECT status, verified_by, edited_by FROM public.review_status WHERE model_run_id = 'r1'") == ("verified", "Lead", "Kai")
        assert one(conn, "SELECT public.set_review_status('v1', 'r1', 'verified', 'Lead')")[0]["changed"] is False
        r = one(conn, "SELECT public.save_human_report_edit('v1', 'r1', %s, 'Kai')", (edit_payload("Edited twice."),))[0]
        assert r["revision"] == 2 and r["status"] == "under review", r
        assert one(conn, "SELECT status, verified_by FROM public.review_status WHERE model_run_id = 'r1'") == ("under review", None)

    @test("source_id: explicit null is a reviewer-added item; unknown or repeated sources are refused")
    def _():
        added = [{"entity_id": "E1", "type": "human", "description": "Attacker", "source_id": "E2"},
                 {"entity_id": "E2", "type": "animal", "description": "Dog", "source_id": None}]
        conn.execute("SELECT public.save_human_report_edit('v1', 'r1', %s, 'Kai')", (edit_payload(entities=added),))
        assert conn.execute("SELECT entity_id, source_entity_id FROM public.human_report_entities ORDER BY 1").fetchall() == [("E1", "E2"), ("E2", None)]
        refused(conn, "SELECT public.save_human_report_edit('v1', 'r1', %s, 'Kai')",
                (edit_payload(entities=[{"entity_id": "E1", "type": "human", "description": "x", "source_id": "E9"}]),), contains="not an AI entity")
        refused(conn, "SELECT public.save_human_report_edit('v1', 'r1', %s, 'Kai')",
                (edit_payload(entities=[{"entity_id": "E1", "type": "human", "description": "x", "source_id": "E1"},
                                        {"entity_id": "E2", "type": "human", "description": "y", "source_id": "E1"}]),), contains="more than one")
        refused(conn, "SELECT public.save_human_report_edit('v1', 'r1', %s, 'Kai')",
                (edit_payload(entities=[{"entity_id": "E2", "source_id": "E2", "type": "human", "description": "x"}]),), contains="not sequential")

    @test("re-analysing a run that has a reviewer version is refused (it would cascade it away)")
    def _():
        refused(conn, "SELECT public.insert_incident('v1', 'r1', 'assault', '1', '9', 8, 'again', 3, 0.8)", contains="reviewer version")

    @test("verifying a legacy AI report copies it with normalised IDs, labels and seconds")
    def _():
        conn.execute("SELECT public.insert_incident('v2', 'r2', 'fighting', '0:00', '0:18', 18, 'Legacy.', 3, 0.95)")
        conn.execute("""INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description) VALUES
            ('v2', 'e02', 'r2', 'person', 'second'), ('v2', 'e01', 'r2', 'person', 'first')""")
        conn.execute("INSERT INTO public.instruments VALUES ('v2', 'i01', 'r2', 'e02', 'knife', 'held', 3, NULL)")
        r = one(conn, "SELECT public.set_review_status('v2', 'r2', 'verified', 'Lead')")[0]
        assert r["humanVersionCreated"], r
        assert one(conn, "SELECT type, start_seconds, end_seconds, duration, created_by, edited_by FROM public.human_reports WHERE model_run_id = 'r2'") == (
            "assault", 0, 18, 18, "Lead", None)
        assert conn.execute("SELECT entity_id, source_entity_id, type FROM public.human_report_entities WHERE model_run_id = 'r2' ORDER BY 1").fetchall() == [
            ("E1", "e01", "human"), ("E2", "e02", "human")]
        assert one(conn, "SELECT instrument_id, source_instrument_id, entity_id FROM public.human_report_instruments WHERE model_run_id = 'r2'") == ("I1", "i01", "E2")
        assert one(conn, "SELECT type FROM public.incidents WHERE model_run_id = 'r2'")[0] == "fighting"  # AI row untouched
        assert one(conn, "SELECT edited_by FROM public.review_status WHERE model_run_id = 'r2'")[0] is None

    @test("a legacy report that is not valid as it stands cannot be verified until edited")
    def _():
        conn.execute("SELECT public.insert_incident('v3', 'r3', 'assault', '0', '5', 5, 'x', 2, NULL)")
        conn.execute("INSERT INTO public.instruments VALUES ('v3', 'I1', 'r3', NULL, 'stick', 'held', NULL, NULL)")
        refused(conn, "SELECT public.set_review_status('v3', 'r3', 'verified', 'Lead')", contains="Instruments I1")
        assert one(conn, "SELECT status FROM public.review_status WHERE model_run_id = 'r3'")[0] == "unreviewed"
        assert one(conn, "SELECT count(*) FROM public.human_reports WHERE model_run_id = 'r3'")[0] == 0

    def sources(run):
        return conn.execute("SELECT entity_id, source_entity_id FROM public.human_report_entities WHERE model_run_id = %s ORDER BY 1", (run,)).fetchall()

    def crops(incident_id, run, items):
        for item_id, x in items:
            conn.execute("""INSERT INTO public.evidence_crops (incident_id, model_run_id, item_type, item_id, item_name, description,
                timestamp_seconds, bounding_box, image, embedding) VALUES (%s, %s, 'entity', %s, 'human', 'ai text', 2, '{0,0,10,10}', 'k', %s)""",
                (incident_id, run, item_id, vec(x)))
        conn.execute("INSERT INTO public.reports (id, incident_id, model_run_id) VALUES (%s, %s, %s)", ("rep-" + run, incident_id, run))
        conn.execute("SELECT public.select_official_report(%s, %s, 'rev')", (incident_id, run))

    def legacy_run(incident_id, run):
        conn.execute("INSERT INTO public.videos (id, filepath) VALUES (%s, %s)", (incident_id, f"uploads/s/{incident_id}.mp4"))
        conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES (%s, 'm')", (run,))
        conn.execute("SELECT public.insert_incident(%s, %s, 'fighting', '0:00', '0:18', 18, 'Legacy.', 3, 0.95)", (incident_id, run))
        conn.execute("""INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description) VALUES
            (%s, 'e01', %s, 'person', 'first'), (%s, 'e02', %s, 'person', 'second')""", (incident_id, run, incident_id, run))
        crops(incident_id, run, [("e01", 1.0), ("e02", 0.9)])

    @test("an edit with an item that has no source_id is refused with the console-update message, through either RPC name")
    def _():
        legacy_run("v4", "r4")
        conn.execute("SELECT public.set_review_status('v4', 'r4', 'verified', 'Lead')")
        before = sources("r4"), one(conn, "SELECT status, revision FROM public.review_status JOIN public.human_reports USING (incident_id, model_run_id) WHERE model_run_id = 'r4'")
        assert before[0] == [("E1", "e01"), ("E2", "e02")], before
        # What the midterm console sends: items renumbered by position, no source_id.
        keyless = edit_payload(entities=[{"entity_id": "E1", "type": "human", "description": "second"}], assets=[])
        for rpc in ("save_human_report_edit", "apply_structured_report_edit"):
            error = refused(conn, f"SELECT public.{rpc}('v4', 'r4', %s, 'Kai')", (keyless,), contains="Items E1 have no source_id")
            assert "Update incident-console-v2" in error, error
        # One keyless item is enough, and a source_id that is not text or null counts as missing.
        refused(conn, "SELECT public.save_human_report_edit('v4', 'r4', %s, 'Kai')", (edit_payload(entities=[
            {"entity_id": "E1", "source_id": "e01", "type": "human", "description": "first"},
            {"entity_id": "E2", "source_id": 2, "type": "human", "description": "second"}], assets=[]),), contains="Items E2 have no source_id")
        after = sources("r4"), one(conn, "SELECT status, revision FROM public.review_status JOIN public.human_reports USING (incident_id, model_run_id) WHERE model_run_id = 'r4'")
        assert after == before, after

    @test("a legacy e01 run's first edit with source ids keeps its crops searchable; a reviewer-added item has no source")
    def _():
        legacy_run("v6", "r6")
        conn.execute("SELECT public.save_human_report_edit('v6', 'r6', %s, 'Kai')", (edit_payload(entities=[
            {"entity_id": "E1", "source_id": "e01", "type": "animal", "description": "first, edited"},
            {"entity_id": "E2", "source_id": "e02", "type": "human", "description": "second"},
            {"entity_id": "E3", "source_id": None, "type": "human", "description": "added"}], assets=[]),))
        assert sources("r6") == [("E1", "e01"), ("E2", "e02"), ("E3", None)], sources("r6")
        assert search("v6") == [("entity", "e01", "animal", "first, edited", "Edited.", None),
                                ("entity", "e02", "human", "second", "Edited.", None)], search("v6")

    @test("a contract run whose E1 is deleted stores E2's origin, so search shows E2's crop with E2's text")
    def _():
        conn.execute("INSERT INTO public.videos (id, filepath) VALUES ('v5', 'uploads/s/v5.mp4')")
        conn.execute("INSERT INTO public.model_runs (id, model_name) VALUES ('r5', 'm')")
        conn.execute("SELECT public.insert_incident('v5', 'r5', 'assault', '1', '9', 8, 'AI.', 3, 0.8)")
        conn.execute("""INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description) VALUES
            ('v5', 'E1', 'r5', 'human', 'Attacker'), ('v5', 'E2', 'r5', 'human', 'Bystander')""")
        crops("v5", "r5", [("E1", 1.0), ("E2", 0.9)])
        # The reviewer deletes E1 on the first edit: the old E2 is renumbered E1 and keeps its origin.
        conn.execute("SELECT public.save_human_report_edit('v5', 'r5', %s, 'Kai')", (edit_payload(entities=[
            {"entity_id": "E1", "source_id": "E2", "type": "human", "description": "Bystander, now E1"}], assets=[]),))
        assert sources("r5") == [("E1", "E2")], sources("r5")
        assert search("v5") == [("entity", "E2", "human", "Bystander, now E1", "Edited.", None)], search("v5")
        # A later edit that adds an item keeps the link it is sent and gives the new item none.
        conn.execute("SELECT public.save_human_report_edit('v5', 'r5', %s, 'Kai')", (edit_payload(entities=[
            {"entity_id": "E1", "source_id": "E2", "type": "human", "description": "Bystander again"},
            {"entity_id": "E2", "source_id": None, "type": "animal", "description": "Dog"}], assets=[]),))
        assert sources("r5") == [("E1", "E2"), ("E2", None)], sources("r5")
        assert search("v5") == [("entity", "E2", "human", "Bystander again", "Edited.", None)], search("v5")

    @test("deleting a run removes its reviewer version and clears the official selection")
    def _():
        conn.execute("SELECT public.save_human_report_edit('v1', 'r1', %s, 'Kai')", (edit_payload(
            entities=[{"entity_id": "E1", "type": "human", "description": "a", "source_id": "E1"},
                      {"entity_id": "E2", "type": "human", "description": "b", "source_id": "E2"}],
            instruments=[{"instrument_id": "I1", "entity_id": "E2", "name": "bat", "description": "c", "threat_level": 2, "source_id": "I1"}]),))
        conn.execute("SELECT public.select_official_report('v1', 'r1', 'rev')")
        conn.execute("DELETE FROM public.incidents WHERE model_run_id = 'r1'")
        assert one(conn, "SELECT count(*) FROM public.human_reports WHERE model_run_id = 'r1'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.human_report_entities WHERE model_run_id = 'r1'")[0] == 0
        assert one(conn, "SELECT selected_model_run_id FROM public.videos WHERE id = 'v1'")[0] is None

    @test("deleting a whole video removes its runs, reviewer versions and crops")
    def _():
        conn.execute("DELETE FROM public.videos WHERE id = 'v2'")
        assert one(conn, "SELECT count(*) FROM public.human_reports WHERE incident_id = 'v2'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.incidents WHERE incident_id = 'v2'")[0] == 0

    conn.execute("RESET ROLE")

    # The copy's guards: copy/transform.sql on hand-made src_* rows, rolled back each time.
    spec = importlib.util.spec_from_file_location("copy_midterm_to_finals", COPY / "copy_midterm_to_finals.py")
    copy_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy_script)
    transform = (COPY / "transform.sql").read_text()

    def run_transform(rows: str) -> str:
        sql = "".join(f"CREATE TEMP TABLE src_{t} (LIKE public.{t});" for t in copy_script.TABLES) + rows + transform
        return refused(conn, sql)

    @test("copy: a run that names a left-behind video in its notes is caught, however the JSON is spaced")
    def _():
        error = run_transform("""INSERT INTO src_videos (id, filepath) VALUES ('v833746b6eaad1531436', 'uploads/x.mp4');
            INSERT INTO src_model_runs (id, model_name, notes) VALUES ('rv', 'm', '{"incidentConsoleV2": {"videoId": "v833746b6eaad1531436"}}');""")
        assert "Videos to leave behind are in use: v833746b6eaad1531436" in error, error

    @test("copy: a run that keeps an edit stamp but gets no reviewer version stops the copy")
    def _():
        base = """INSERT INTO src_videos (id, filepath) VALUES ('vc', 'uploads/c.mp4');
            INSERT INTO src_model_runs (id, model_name, notes) VALUES ('rc', 'm', %s);
            INSERT INTO src_incidents (incident_id, model_run_id, type, start_timestamp, end_timestamp, duration, description, severity_level)
                VALUES ('vc', 'rc', 'assault', '0', '5', 5, 'maybe edited', 3);
            INSERT INTO src_review_status (incident_id, model_run_id, status, edited_by, edited_at) VALUES ('vc', 'rc', 'under review', 'Kai', '2026-10-01');"""
        for notes in ("NULL",  # a legacy run edited on midterm
                      """'{"incidentConsoleV2": {"contractVersion": "v3"}}'"""):  # a valid run with no report in notes
            error = run_transform(base % notes)
            assert "keep an edit stamp but have no reviewer version (rc (vc, Kai))" in error, error

    # m37883594f65802c8a31 on midterm: a legacy run verified by the same name, at the same instant, as its edit stamp.
    legacy_stamped = """INSERT INTO src_videos (id, filepath) VALUES ('vl', 'uploads/l.mp4');
        INSERT INTO src_model_runs (id, model_name, notes) VALUES ('rl', 'm', NULL);
        INSERT INTO src_incidents (incident_id, model_run_id, type, start_timestamp, end_timestamp, duration, description, severity_level)
            VALUES ('vl', 'rl', 'fighting', '0:00', '0:18', 18, 'verified, maybe edited first', 3);
        INSERT INTO src_review_status (incident_id, model_run_id, status, edited_by, edited_at, verified_by, verified_at)
            VALUES ('vl', 'rl', 'verified', 'Lead', '2026-10-01 08:39:24', 'Lead', '2026-10-01 08:39:24');"""

    def transformed(rows: str, decisions: str = "") -> list[tuple]:
        sql = "".join(f"CREATE TEMP TABLE src_{t} (LIKE public.{t});" for t in copy_script.TABLES)
        sql += "CREATE TEMP TABLE migration_stamp_decisions (model_run_id TEXT PRIMARY KEY, decision TEXT NOT NULL);" + decisions
        with conn.transaction(force_rollback=True):
            conn.execute(sql + rows + transform)
            return conn.execute("""SELECT rs.edited_by, h.created_by, h.edited_by FROM public.review_status rs
                LEFT JOIN public.human_reports h USING (incident_id, model_run_id) WHERE rs.model_run_id = 'rl'""").fetchall()

    @test("copy: a legacy run whose edit stamp equals its verification stops the copy until a person decides")
    def _():
        error = run_transform(legacy_stamped)
        assert "keep an edit stamp but have no reviewer version (rl (vl, Lead))" in error, error
        assert "--not-edited or --edited" in error, error

    @test("copy: --not-edited clears the legacy stamp and verifies a copy; --edited keeps it as the reviewer's edit")
    def _():
        assert transformed(legacy_stamped, "INSERT INTO migration_stamp_decisions VALUES ('rl', 'not edited');") == [(None, "Lead", None)]
        assert transformed(legacy_stamped, "INSERT INTO migration_stamp_decisions VALUES ('rl', 'edited');") == [("Lead", "Lead", "Lead")]
        error = refused(conn, "".join(f"CREATE TEMP TABLE src_{t} (LIKE public.{t});" for t in copy_script.TABLES)
                        + "CREATE TEMP TABLE migration_stamp_decisions (model_run_id TEXT PRIMARY KEY, decision TEXT NOT NULL);"
                        + "INSERT INTO migration_stamp_decisions VALUES ('nope', 'not edited');" + legacy_stamped + transform)
        assert "Stamp decisions name runs that are not stamped non-contract runs: nope" in error, error

    # mcd6cb9073218402f7bf on midterm: a verified contract run whose stored items were removed
    # after the copy plan was made (the AI wrote E1, E2 and A1-A3), stamp = verification.
    ai_report = {"incident": {"type": "animal attack", "start_timestamp": "0", "end_timestamp": "9", "duration": 9,
                              "description": "Bear in kitchen.", "severity_level": 4},
                 "entities": [{"entity_id": "E1", "type": "animal", "description": "bear"},
                              {"entity_id": "E2", "type": "human", "description": "person at door"}],
                 "instruments": [],
                 "assets": [{"asset_id": "A1", "name": "fridge", "description": "steel"},
                            {"asset_id": "A2", "name": "island", "description": "wood"},
                            {"asset_id": "A3", "name": "door", "description": "white"}]}

    def item_edited(entities: str, assets: str = "") -> str:
        notes = json.dumps({"incidentConsoleV2": {"contractVersion": "v2", "report": ai_report}}).replace("'", "''")
        return f"""INSERT INTO src_videos (id, filepath, selected_model_run_id) VALUES ('vb', 'uploads/b.mp4', 'rb');
            INSERT INTO src_model_runs (id, model_name, notes) VALUES ('rb', 'm', '{notes}');
            INSERT INTO src_incidents (incident_id, model_run_id, type, start_timestamp, end_timestamp, duration, description, severity_level)
                VALUES ('vb', 'rb', 'animal attack', '0', '9', 9, 'Bear in kitchen.', 4);
            INSERT INTO src_review_status (incident_id, model_run_id, status, edited_by, edited_at, verified_by, verified_at)
                VALUES ('vb', 'rb', 'verified', 'Lead', '2026-10-01 08:41:40', 'Lead', '2026-10-01 08:41:40');
            {entities}{assets}"""

    def accepted(rows: str) -> tuple:
        sql = "".join(f"CREATE TEMP TABLE src_{t} (LIKE public.{t});" for t in copy_script.TABLES)
        sql += "CREATE TEMP TABLE migration_accepted_item_edits (model_run_id TEXT PRIMARY KEY); INSERT INTO migration_accepted_item_edits VALUES ('rb');"
        with conn.transaction(force_rollback=True):
            conn.execute(sql + rows + transform)
            q = lambda s: conn.execute(s).fetchall()
            return (q("SELECT entity_id, source_entity_id, description FROM public.human_report_entities WHERE model_run_id = 'rb' ORDER BY 1"),
                    q("SELECT asset_id, source_asset_id FROM public.human_report_assets WHERE model_run_id = 'rb' ORDER BY 1"),
                    q("SELECT entity_id, description FROM public.entities WHERE model_run_id = 'rb' ORDER BY 1"),
                    q("SELECT asset_id FROM public.assets WHERE model_run_id = 'rb' ORDER BY 1"),
                    q("SELECT h.edited_by, rs.status, rs.edited_by FROM public.human_reports h JOIN public.review_status rs USING (incident_id, model_run_id) WHERE h.model_run_id = 'rb'"),
                    q("SELECT kind, reviewer_id, ai_id FROM migration_item_links ORDER BY 1, 2"))

    @test("copy: a contract run whose items were all removed stops the copy unless --accept-item-edits names it")
    def _():
        error = run_transform(item_edited(""))
        assert "Item-level reviewer edits found (rb:assets, rb:entities)" in error and "--accept-item-edits" in error, error
        humans, assets, ai_entities, ai_assets, stamps, links = accepted(item_edited(""))
        assert humans == [] and assets == [] and links == [], (humans, assets, links)  # the reviewer version keeps no items
        assert ai_entities == [("E1", "bear"), ("E2", "person at door")] and ai_assets == [("A1",), ("A2",), ("A3",)]  # AI rows from notes
        assert stamps == [("Lead", "verified", "Lead")], stamps

    @test("copy: --accept-item-edits links an item to the AI item with identical content, else leaves it NULL")
    def _():
        # E1 deleted (old E2 is now E1), a new E2 added; A2 edited, A3 deleted.
        rows = item_edited("""INSERT INTO src_entities (incident_id, entity_id, model_run_id, type, description) VALUES
                ('vb', 'E1', 'rb', 'human', 'person at door'), ('vb', 'E2', 'rb', 'animal', 'a dog');""",
                           """INSERT INTO src_assets (incident_id, asset_id, model_run_id, name, description) VALUES
                ('vb', 'A1', 'rb', 'fridge', 'steel'), ('vb', 'A2', 'rb', 'island', 'oak');""")
        humans, assets, ai_entities, ai_assets, _, links = accepted(rows)
        assert humans == [("E1", "E2", "person at door"), ("E2", None, "a dog")], humans
        assert assets == [("A1", "A1"), ("A2", None)], assets
        assert ai_entities == [("E1", "bear"), ("E2", "person at door")] and ai_assets == [("A1",), ("A2",), ("A3",)]
        assert links == [("assets", "A1", "A1"), ("assets", "A2", None), ("entities", "E1", "E2"), ("entities", "E2", None)], links
        # A run without item edits cannot be named.
        error = refused(conn, "".join(f"CREATE TEMP TABLE src_{t} (LIKE public.{t});" for t in copy_script.TABLES)
                        + "CREATE TEMP TABLE migration_accepted_item_edits (model_run_id TEXT PRIMARY KEY); INSERT INTO migration_accepted_item_edits VALUES ('nope');"
                        + transform)
        assert "--accept-item-edits names runs without item-level edits: nope" in error, error

    conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
