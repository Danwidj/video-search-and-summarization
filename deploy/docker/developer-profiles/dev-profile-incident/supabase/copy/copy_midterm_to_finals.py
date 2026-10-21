# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Copy the incident data from the midterm Supabase database into the finals one.

    cd supabase/copy && uv run --no-project --with 'psycopg[binary]' python copy_midterm_to_finals.py \
        --source-env <midterm .env file> --target-env <finals .env file> [--commit] [--replace] \
        [--not-edited <run id> ...] [--edited <run id> ...] [--accept-item-edits <run id> ...]

Both env files hold INCIDENT_DB_DSN (session pooler, port 5432; run from a laptop, kwanz-ws
blocks 5432). DSNs and keys are never printed.

* Midterm is only read, inside one REPEATABLE READ READ ONLY transaction (one consistent snapshot).
* Finals is written inside one transaction: raw rows are streamed into temp tables, transform.sql
  builds the finals rows from them, then every check below runs. Without --commit (the default)
  the transaction is rolled back: a full rehearsal that leaves finals empty.
* Idempotent: it refuses a finals database that already has rows unless --replace, which empties
  the copied tables first in the same transaction. A failed run changes nothing.
* A legacy (non-contract) run that keeps an edit stamp stops the copy: nothing records what the AI
  wrote, so only a person can say whether its rows hold an edit. --not-edited RUN clears the stamp;
  --edited RUN makes the stored rows the reviewer version (the AI's original is then lost).
* A contract run whose items differ from its notes record also stops the copy (an item's AI origin
  cannot be proven). --accept-item-edits RUN copies its stored items as the reviewer version, links
  each to the AI item with identical content where that match is unique (no link otherwise), puts
  the AI items back from notes, and prints every link it made or left empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent

# FK order. Everything public that exists on both sides, except the four legacy pre-v1 tables.
TABLES: dict[str, str] = {
    "videos": "id",
    "queries": "id",
    "model_runs": "id",
    "incidents": "incident_id, model_run_id",
    "reports": "id",
    "entities": "incident_id, model_run_id, entity_id",
    "instruments": "incident_id, model_run_id, instrument_id",
    "assets": "incident_id, model_run_id, asset_id",
    "review_status": "incident_id, model_run_id",
    "notifications": "id",
    "severity_eval_log": "id",
    "gt_incidents": "incident_id",
    "gt_entities": "incident_id, entity_id",
    "gt_instruments": "incident_id, instrument_id",
    "gt_assets": "incident_id, asset_id",
    "entity_matches": "incident_id, model_run_id, entity_id",
    "instrument_matches": "incident_id, model_run_id, instrument_id",
    "asset_matches": "incident_id, model_run_id, asset_id",
    "evidence_crops": "incident_id, model_run_id, item_type, item_id",
    "query_results": "id",
}
FINALS_ONLY = ["human_report_instruments", "human_report_assets", "human_report_entities", "human_reports"]

# Columns the transform may change; every other column must arrive byte-identical.
TRANSFORMED = {
    "videos": {"selected_model_run_id"},  # set in a second step, compared separately
    "incidents": {"type", "start_timestamp", "end_timestamp", "duration", "description", "severity_level"},
    "entities": {"type"},
    "review_status": {"edited_by", "edited_at"},
    "evidence_crops": {"item_name"},
}


def read_dsn(env_file: str) -> str:
    for line in Path(env_file).read_text().splitlines():
        match = re.match(r"^\s*INCIDENT_DB_DSN=(.*)$", line.strip())
        if match:
            return match.group(1).strip().strip('"').strip("'").replace("postgresql+psycopg2://", "postgresql://")
    raise SystemExit(f"INCIDENT_DB_DSN is not set in {env_file}")


def columns(cur: psycopg.Cursor, table: str) -> list[tuple[str, str]]:
    cur.execute(
        """SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a
           WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
        (f"public.{table}",),
    )
    # vector's schema differs (public on midterm, extensions on finals); compare the bare type.
    return [(name, typ.replace("extensions.", "")) for name, typ in cur.fetchall()]


def digest(cur: psycopg.Cursor, relation: str, cols: list[str], order: str, where: str = "TRUE") -> tuple[int, str]:
    """Row count and an md5 over the listed columns' text, in key order."""
    expr = "ROW(" + ", ".join(cols) + ")::TEXT"
    # Byte order, so both servers sort alike whatever their default collation.
    order = ", ".join(f'({key})::TEXT COLLATE "C"' for key in order.split(", "))
    cur.execute(f"SELECT count(*), md5(COALESCE(string_agg({expr}, E'\\n' ORDER BY {order}), '')) FROM {relation} WHERE {where}")
    count, md5 = cur.fetchone()
    return count, md5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-env", required=True, help="env file with the MIDTERM INCIDENT_DB_DSN (read only)")
    parser.add_argument("--target-env", required=True, help="env file with the FINALS INCIDENT_DB_DSN")
    parser.add_argument("--commit", action="store_true", help="commit; without it the run is a rehearsal and rolls back")
    parser.add_argument("--replace", action="store_true", help="empty the copied finals tables first (before go-live only)")
    parser.add_argument("--not-edited", action="append", default=[], metavar="RUN",
                        help="a stamped legacy run a person checked was not edited: clear its stamp (repeatable)")
    parser.add_argument("--edited", action="append", default=[], metavar="RUN",
                        help="a stamped legacy run a person checked was edited: its stored rows become the reviewer version (repeatable)")
    parser.add_argument("--accept-item-edits", action="append", default=[], metavar="RUN",
                        help="a contract run whose item-level edits a person accepted as they stand (repeatable)")
    args = parser.parse_args()
    if set(args.not_edited) & set(args.edited):
        raise SystemExit("a run cannot be both --not-edited and --edited")

    source_dsn, target_dsn = read_dsn(args.source_env), read_dsn(args.target_env)
    if source_dsn == target_dsn:
        raise SystemExit("source and target are the same database")

    failures: list[str] = []

    def check(ok: bool, message: str) -> None:
        print(("  ok    " if ok else "  FAIL  ") + message)
        if not ok:
            failures.append(message)

    with psycopg.connect(source_dsn) as src, psycopg.connect(target_dsn) as dst:
        src.read_only = True
        src.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        scur, dcur = src.cursor(), dst.cursor()
        scur.execute("SELECT 1")  # opens the snapshot every read below shares

        print("preflight")
        dcur.execute("SELECT to_regclass('public.human_reports') IS NOT NULL AND to_regclass('public.incident_reports') IS NULL")
        check(dcur.fetchone()[0], "finals has the finals baseline (human_reports, no legacy tables)")
        dcur.execute("SELECT current_setting('server_version_num')::INT >= 150000")
        check(dcur.fetchone()[0], "finals runs Postgres 15 or later")
        for table in TABLES:
            check(columns(scur, table) == columns(dcur, table), f"{table}: same columns and types on both sides")
        scur.execute("SELECT has_table_privilege('service_role', 'public.incidents', 'INSERT')")
        if scur.fetchone()[0]:
            print("  warn  midterm still accepts service_role writes: freeze it first (supabase/midterm/freeze_midterm.sql)")
        dcur.execute(" UNION ALL ".join(f"SELECT '{t}', count(*) FROM public.{t}" for t in [*TABLES, *FINALS_ONLY]))
        occupied = [f"{t} ({n})" for t, n in dcur.fetchall() if n]
        if occupied and not args.replace:
            raise SystemExit(f"finals already has rows in {', '.join(occupied)}; rerun with --replace before go-live")
        if failures:
            raise SystemExit("preflight failed; nothing was written")

        if args.replace:
            dcur.execute("TRUNCATE " + ", ".join(f"public.{t}" for t in [*FINALS_ONLY, *TABLES]) + " RESTART IDENTITY")

        print("copy (midterm snapshot -> finals temp tables)")
        source_digest: dict[str, tuple[int, str]] = {}
        for table, order in TABLES.items():
            cols = [c for c, _ in columns(scur, table)]
            source_digest[table] = digest(scur, f"public.{table}", cols, order)
            dcur.execute(f"CREATE TEMP TABLE src_{table} (LIKE public.{table})")
            with scur.copy(f"COPY (SELECT * FROM public.{table} ORDER BY {order}) TO STDOUT") as out, \
                    dcur.copy(f"COPY src_{table} FROM STDIN") as into:
                for block in out:
                    into.write(block)
            got = digest(dcur, f"src_{table}", cols, order)
            check(got == source_digest[table], f"{table}: {got[0]} rows arrived, checksum matches midterm")
        src.rollback()
        if failures:
            raise SystemExit("raw copy did not match midterm; rolled back")

        print("transform")
        dcur.execute("CREATE TEMP TABLE migration_stamp_decisions (model_run_id TEXT PRIMARY KEY, decision TEXT NOT NULL)")
        decisions = [(run, "not edited") for run in args.not_edited] + [(run, "edited") for run in args.edited]
        dcur.executemany("INSERT INTO migration_stamp_decisions VALUES (%s, %s)", decisions)
        for run, decision in decisions:
            print(f"  stamp decision: {run} {decision}")
        dcur.execute("CREATE TEMP TABLE migration_accepted_item_edits (model_run_id TEXT PRIMARY KEY)")
        dcur.executemany("INSERT INTO migration_accepted_item_edits VALUES (%s)", [(run,) for run in args.accept_item_edits])
        for run in args.accept_item_edits:
            print(f"  accepted item edits: {run}")
        dcur.execute((HERE / "transform.sql").read_text())

        print("checks")
        dcur.execute("SELECT reason, count(*) FROM migration_excluded_runs GROUP BY 1 ORDER BY 1")
        excluded_runs = dict(dcur.fetchall())
        dcur.execute("SELECT count(*) FROM migration_excluded_videos")
        excluded_videos = dcur.fetchone()[0]
        print(f"  left behind: runs {excluded_runs}, broken uploads {excluded_videos}")
        expected_rows = {t: source_digest[t][0] for t in TABLES}
        expected_rows["model_runs"] -= sum(excluded_runs.values())
        expected_rows["videos"] -= excluded_videos
        for table, order in TABLES.items():
            all_cols = [c for c, _ in columns(dcur, table)]
            kept = [c for c in all_cols if c not in TRANSFORMED.get(table, set())]
            where = "TRUE"
            both_sides = table in ("entities", "instruments", "assets")
            if both_sides:  # rows of accepted item edits are rebuilt from notes, checked below
                where = f"model_run_id NOT IN (SELECT model_run_id FROM migration_restored_items WHERE kind = '{table}')"
            if table == "model_runs":
                where = "id NOT IN (SELECT id FROM migration_excluded_runs)"
            if table == "videos":
                where = "id NOT IN (SELECT id FROM migration_excluded_videos)"
            want = digest(dcur, f"src_{table}", kept, order, where)
            got = digest(dcur, f"public.{table}", kept, order, where if both_sides else "TRUE")
            expected = want[0] if both_sides else expected_rows[table]
            check(got[0] == expected, f"{table}: {got[0]} rows (expected {expected})")
            check(got == want, f"{table}: untouched columns identical to midterm")

        dcur.execute("""SELECT count(*) FILTER (WHERE s.selected_model_run_id IS DISTINCT FROM v.selected_model_run_id)
                        FROM public.videos v JOIN src_videos s USING (id)""")
        check(dcur.fetchone()[0] == 0, "official selections identical")
        dcur.execute("SELECT count(*) FROM public.incidents WHERE type IN ('fighting', 'animal')")
        check(dcur.fetchone()[0] == 0, "no legacy incident types left")
        dcur.execute("SELECT count(*) FROM public.entities WHERE type = 'person'")
        check(dcur.fetchone()[0] == 0, "no legacy entity types left")
        dcur.execute("""SELECT
            (SELECT count(*) FROM src_incidents WHERE type IN ('fighting', 'animal')),
            (SELECT count(*) FROM src_entities WHERE type = 'person'),
            (SELECT count(*) FROM src_evidence_crops WHERE item_type = 'entity' AND item_name = 'person')""")
        incidents, entities, crops = dcur.fetchone()
        print(f"  relabelled: incidents {incidents}, entities {entities}, crops {crops}")
        dcur.execute("SELECT model_run_id, string_agg(field, ',' ORDER BY field) FROM migration_run_diffs GROUP BY 1 ORDER BY 1")
        edited = dcur.fetchall()
        print(f"  edited reports (AI rows restored from notes): {edited}")
        dcur.execute("SELECT model_run_id, kind, reviewer_id, ai_id FROM migration_item_links ORDER BY 1, 2, 3")
        links = dcur.fetchall()
        dcur.execute("SELECT model_run_id, kind FROM migration_restored_items ORDER BY 1, 2")
        print(f"  accepted item edits: AI items restored from notes for {dcur.fetchall()}; reviewer item links: {len(links)}")
        for run, kind, reviewer_id, ai_id in links:
            print(f"        {run} {kind} {reviewer_id} -> {ai_id or 'NULL (no unique AI item with identical content)'}")
        for kind, key, cols in (("entities", "entity_id", "x->>'entity_id', CASE x->>'type' WHEN 'person' THEN 'human' ELSE x->>'type' END, x->>'description'"),
                                ("instruments", "instrument_id", "x->>'instrument_id', x->>'entity_id', x->>'name', x->>'description', (x->>'threat_level')::INT"),
                                ("assets", "asset_id", "x->>'asset_id', x->>'name', x->>'description'")):
            stored = {"entities": "entity_id, type, description", "instruments": "instrument_id, entity_id, name, description, threat_level",
                      "assets": "asset_id, name, description"}[kind]
            dcur.execute(f"""SELECT count(*) FROM migration_restored_items r WHERE r.kind = '{kind}' AND
                (SELECT COALESCE(array_agg(ROW({stored})::TEXT ORDER BY {key}), '{{}}') FROM public.{kind} t WHERE t.model_run_id = r.model_run_id)
                IS DISTINCT FROM
                (SELECT COALESCE(array_agg(ROW({cols})::TEXT ORDER BY x->>'{key}'), '{{}}') FROM jsonb_array_elements(COALESCE(r.report->'{kind}', '[]')) x)""")
            check(dcur.fetchone()[0] == 0, f"{kind}: AI rows of accepted item edits equal their notes record")
        dcur.execute("SELECT model_run_id, edited_by, edited_at, reason FROM migration_cleared_stamps ORDER BY model_run_id")
        cleared = dcur.fetchall()
        print(f"  edit stamps cleared: {len(cleared)}")
        for row in cleared:
            print(f"        {row[0]} {row[1]} {row[2]} ({row[3]})")
        dcur.execute("""SELECT h.model_run_id, h.created_by, h.edited_by IS NOT NULL, rs.status
                        FROM public.human_reports h JOIN public.review_status rs USING (incident_id, model_run_id) ORDER BY 1""")
        humans = dcur.fetchall()
        print(f"  reviewer versions: {len(humans)}")
        for row in humans:
            print(f"        {row[0]} by {row[1]} edited={row[2]} status={row[3]}")
        dcur.execute("""SELECT count(*) FROM public.review_status rs WHERE rs.status = 'verified'
                        AND NOT EXISTS (SELECT 1 FROM public.human_reports h WHERE h.incident_id = rs.incident_id AND h.model_run_id = rs.model_run_id)""")
        check(dcur.fetchone()[0] == 0, "every verified report has a reviewer version")
        # Every contract run's AI rows now equal its notes record.
        dcur.execute("""SELECT count(*) FROM public.incidents i JOIN public.model_runs mr ON mr.id = i.model_run_id
            WHERE public.run_outcome(mr.notes) IN ('valid_first_pass', 'valid_after_structural_repair')
              AND jsonb_typeof(public.try_parse_jsonb(mr.notes) #> '{incidentConsoleV2,report,incident}') = 'object'
              AND (i.description IS DISTINCT FROM public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,description}'
                OR i.type IS DISTINCT FROM public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,type}'
                OR i.severity_level IS DISTINCT FROM (public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,severity_level}')::INT)""")
        check(dcur.fetchone()[0] == 0, "every contract run's AI rows equal its immutable notes record")
        dcur.execute("""SELECT count(*) FROM public.effective_incidents e JOIN src_incidents s USING (incident_id, model_run_id)
            WHERE e.description IS DISTINCT FROM s.description OR public.canonical_incident_type(e.type) IS DISTINCT FROM public.canonical_incident_type(s.type)
               OR e.severity_level IS DISTINCT FROM s.severity_level OR e.duration IS DISTINCT FROM s.duration""")
        check(dcur.fetchone()[0] == 0, "effective reports equal what midterm showed (edits kept)")

        if failures:
            dst.rollback()
            print(f"\n{len(failures)} check(s) failed; rolled back, finals unchanged")
            return 1
        if args.commit:
            dst.commit()
            print("\ncommitted")
        else:
            dst.rollback()
            print("\nall checks passed; rehearsal rolled back (use --commit to keep)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
