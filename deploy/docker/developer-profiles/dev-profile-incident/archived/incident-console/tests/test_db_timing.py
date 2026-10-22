# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""``scripts/db_timing.py`` is run by a person against a real DSN, so its one hard promise is tested here:
nothing that identifies the database (DSN, host, user, password, database name, IP) reaches the output."""

from __future__ import annotations

import socket
import threading

import pytest
from sqlalchemy.engine import make_url

from db import IncidentDB
from scripts.db_timing import describe_endpoint, main, redact

USER, PASSWORD, DATABASE = "zz_user_7f3a", "s3cr3t-pw-91", "zz_db_9x"
SECRETS = (USER, PASSWORD, DATABASE)


def use_dsn(monkeypatch, dsn: str) -> None:
    monkeypatch.setattr("config.incident_db_dsn", lambda: dsn)


def test_redact_replaces_every_identifying_value_and_any_ip():
    url = make_url(f"postgresql+psycopg2://{USER}:{PASSWORD}@db.projref.supabase.co:5432/{DATABASE}")
    message = (
        f'connection to server at "db.projref.supabase.co" (203.0.113.7), port 5432 failed: '
        f'FATAL: password authentication failed for user "{USER}" ({PASSWORD}) database {DATABASE} '
        f"also 2001:db8:0:1::7"
    )
    cleaned = redact(message, url)
    for secret in (*SECRETS, "projref", "203.0.113.7", "2001:db8"):
        assert secret not in cleaned
    assert "<host>" in cleaned
    assert "<user>" in cleaned


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        (
            "postgresql+psycopg2://u:p@aws-0-x.pooler.supabase.com:5432/postgres",
            "shared pooler (Supavisor), session mode",
        ),
        (
            "postgresql+psycopg2://u:p@aws-1-x.pooler.supabase.com:6543/postgres",
            "shared pooler (Supavisor), transaction mode",
        ),
        ("postgresql+psycopg2://u:p@db.projref.supabase.co:5432/postgres", "Supabase direct connection"),
        ("postgresql+psycopg2://u:p@example.internal:5432/postgres", "other host"),
        ("sqlite:///x.db", "no network host"),
    ],
)
def test_the_endpoint_kind_is_named_without_naming_the_host(dsn, expected):
    described = describe_endpoint(make_url(dsn))
    assert expected in described
    assert "projref" not in described
    assert "example.internal" not in described


def test_a_missing_dsn_is_reported_and_nothing_is_attempted(monkeypatch, capsys):
    use_dsn(monkeypatch, "")
    assert main([]) == 2
    assert "INCIDENT_DB_DSN is not set" in capsys.readouterr().err


@pytest.mark.parametrize("show_errors", [False, True])
def test_a_refused_connection_prints_no_secret(monkeypatch, capsys, show_errors):
    use_dsn(monkeypatch, f"postgresql+psycopg2://{USER}:{PASSWORD}@localhost:1/{DATABASE}?sslmode=disable")
    assert main(["--show-errors"] if show_errors else []) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "failed (ConnectionRefusedError)" in output
    for secret in (*SECRETS, "localhost"):
        assert secret not in output


def test_a_server_that_hangs_up_prints_no_secret_even_with_show_errors(monkeypatch, capsys):
    """The real libpq message names the host and its IP address; both must come out redacted."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def hang_up() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=hang_up, daemon=True).start()
    port = listener.getsockname()[1]
    use_dsn(monkeypatch, f"postgresql+psycopg2://{USER}:{PASSWORD}@localhost:{port}/{DATABASE}?sslmode=disable")

    try:
        assert main(["--show-errors"]) == 1
    finally:
        listener.close()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "query failed (OperationalError)" in output
    for secret in (*SECRETS, "localhost", "127.0.0.1", "Traceback"):
        assert secret not in output


def test_a_working_database_prints_the_comparison_and_not_the_dsn(monkeypatch, capsys, tmp_path):
    path = tmp_path / "timing.db"
    IncidentDB.from_dsn(f"sqlite:///{path}").init_schema()
    use_dsn(monkeypatch, f"sqlite:///{path}")

    assert main(["--samples", "3"]) == 0

    out = capsys.readouterr().out
    assert "warm SELECT 1, console settings now" in out
    assert "warm SELECT 1, previous settings" in out
    assert "incident list query now (0 rows)" in out
    assert "40 queries: previous settings" in out
    assert str(path) not in out
    assert "sqlite:///" not in out


def test_the_idle_test_reports_whether_a_held_connection_survived(monkeypatch, capsys, tmp_path):
    path = tmp_path / "idle.db"
    IncidentDB.from_dsn(f"sqlite:///{path}").init_schema()
    use_dsn(monkeypatch, f"sqlite:///{path}")
    assert main(["--samples", "3", "--idle", "1"]) == 0
    assert "idle     1 s: connection alive" in capsys.readouterr().out
