# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Full rehearsal of the finals switch on a throwaway local Postgres; midterm is only read.

    cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python rehearse.py <midterm env file> [copy flags, e.g. --not-edited <run id>]

fresh Postgres + Supabase stub -> supabase/migrations/ -> copy (committed locally) -> security audit
-> reader parity against midterm -> copy again with --replace (rolled back) to prove reruns are safe.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
midterm_env = sys.argv[1]
decisions = sys.argv[2:]  # passed to every copy run: the stamp decisions (--not-edited / --edited)

with tempfile.TemporaryDirectory() as tmp:
    server = pgserver.get_server(tmp, cleanup_mode="stop")
    with psycopg.connect(server.get_uri(), autocommit=True) as conn:
        conn.execute((HERE / "supabase_stub.sql").read_text())
        with conn.transaction():
            for migration in sorted((ROOT / "migrations").glob("*.sql")):
                conn.execute(migration.read_text())
        print("finals migrations applied")
    env = Path(tmp) / "finals.env"
    env.write_text(f"INCIDENT_DB_DSN={server.get_uri()}\n")
    copy = [sys.executable, "-I", str(ROOT / "copy" / "copy_midterm_to_finals.py"), "--source-env", midterm_env, "--target-env", str(env), *decisions]
    subprocess.run([*copy, "--commit"], check=True)
    with psycopg.connect(server.get_uri()) as conn:
        problems = conn.execute((HERE / "security_check.sql").read_text()).fetchall()
        print(f"security_check.sql after the copy: {len(problems)} problem(s) {problems}")
        print("finals row counts:", dict(conn.execute(
            "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE schemaname = 'public' ORDER BY relname").fetchall()))
    subprocess.run([sys.executable, "-I", str(HERE / "parity_check.py"), "--source-env", midterm_env, "--target-env", str(env)], check=True)
    subprocess.run([*copy, "--replace"], check=True)
