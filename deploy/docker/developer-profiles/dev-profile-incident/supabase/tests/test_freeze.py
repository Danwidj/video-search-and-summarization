# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""freeze_midterm.sql / unfreeze_midterm.sql on a local replica of midterm (schema rebuilt from
midterm/midterm_base_tables.sql + the applied midterm/migrations/).

    cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_freeze.py
"""

import tempfile
from pathlib import Path

import pgserver
import psycopg
from psycopg import errors

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MIGRATIONS = ROOT / "midterm" / "migrations"
APPLIED = ["20260917141225", "20260925031000", "20260926120000", "20260927120000", "20260927130000", "20260927140000",
           "20260927150000", "20260927160000", "20260927170000", "20260927180000", "20260928000000", "20261016120000"]

with tempfile.TemporaryDirectory() as tmp:
    server = pgserver.get_server(tmp, cleanup_mode="stop")
    uri = server.get_uri()
    # The real midterm 'postgres' is not a superuser; use a non-superuser owner like it.
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute((HERE / "supabase_stub.sql").read_text())
        admin.execute("CREATE ROLE owner_pg LOGIN CREATEROLE BYPASSRLS; GRANT CREATE, USAGE ON SCHEMA public TO owner_pg; GRANT anon, authenticated, service_role TO owner_pg")
        admin.execute("CREATE EXTENSION vector")  # superuser-owned, as supabase_admin owns it on midterm
        admin.execute("ALTER DEFAULT PRIVILEGES FOR ROLE owner_pg IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role")
        admin.execute("ALTER DEFAULT PRIVILEGES FOR ROLE owner_pg IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role")
        admin.execute("ALTER DEFAULT PRIVILEGES FOR ROLE owner_pg IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role")
    owner_uri = uri.replace("postgres:@", "owner_pg:@", 1)
    with psycopg.connect(owner_uri, autocommit=True) as conn:
        conn.execute((ROOT / "midterm" / "midterm_base_tables.sql").read_text())
        for version in APPLIED:
            conn.execute(next(MIGRATIONS.glob(f"{version}_*.sql")).read_text())
        conn.execute("INSERT INTO videos (id) VALUES ('v1'); INSERT INTO model_runs (id, model_name) VALUES ('r1', 'm')")
        conn.execute("SELECT insert_incident('v1', 'r1', 'assault', '0', '1', 1, 'd', 3, 0.5)")
        freeze = (ROOT / "midterm" / "freeze_midterm.sql").read_text().replace("ALTER ROLE postgres", "ALTER ROLE owner_pg")
        conn.execute(freeze)
    with psycopg.connect(owner_uri, autocommit=True) as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        try:
            conn.execute("INSERT INTO videos (id) VALUES ('v2')")
            raise AssertionError("owner session could write")
        except errors.ReadOnlySqlTransaction:
            print("ok   direct-DSN sessions are read-only")
        conn.execute("SET ROLE service_role")
        conn.execute("SET default_transaction_read_only = off")
        assert conn.execute("SELECT count(*) FROM incidents").fetchone()[0] == 1
        assert conn.execute("SELECT list_incident_report_summaries(p_page_size => 6)").fetchone()[0] is not None
        for sql in ("INSERT INTO videos (id) VALUES ('v3')", "SELECT insert_incident('v1', 'r1', 'assault', '0', '1', 1, 'd', 3, 0.5)",
                    "SELECT select_official_report('v1', 'r1', 'x')", "DELETE FROM videos WHERE id = 'v1'"):
            try:
                conn.execute(sql)
                raise AssertionError(f"service_role could run: {sql}")
            except errors.InsufficientPrivilege:
                pass
        print("ok   service_role reads and runs the read RPCs, every write is refused")
        conn.execute("SET ROLE anon")
        for sql in ("SELECT 1 FROM videos", "SELECT list_incident_report_summaries()"):
            try:
                conn.execute(sql)
                raise AssertionError(f"anon could run: {sql}")
            except errors.InsufficientPrivilege:
                pass
        print("ok   anon is locked out")
        conn.execute("RESET ROLE")
        conn.execute((ROOT / "midterm" / "unfreeze_midterm.sql").read_text().replace("ALTER ROLE postgres", "ALTER ROLE owner_pg"))
    with psycopg.connect(owner_uri, autocommit=True) as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "off"
        conn.execute("SET ROLE service_role")
        conn.execute("INSERT INTO videos (id) VALUES ('v4')")
        conn.execute("SELECT insert_incident('v4', 'r1', 'assault', '0', '1', 1, 'd', 3, 0.5)")
        print("ok   unfreeze restores writes")
