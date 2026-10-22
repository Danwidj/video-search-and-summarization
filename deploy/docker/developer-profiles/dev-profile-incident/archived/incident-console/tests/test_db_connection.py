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

"""Round-trip and dropped-connection behaviour of the DB layer (``db_connection.py``).

Hermetic: SQLite stands in for Postgres. A dropped pooled connection is simulated by
closing the driver connection *underneath* the pool, which is what a server-side kill or
an idle-timeout looks like to the client. The wire-level claims (round trips per statement)
are measured against real PostgreSQL by ``scripts/measure_db_roundtrips.py`` and checked in
``tests/test_db_postgres_integration.py``, not here.
"""

from __future__ import annotations

import inspect
import logging
import sqlite3
import time
from dataclasses import dataclass, field

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.engine import Engine, make_url
from streamlit.testing.v1 import AppTest

import config
import db
import db_connection
import ui
from db import IncidentDB, metadata, videos
from db_connection import WriteOnReadEngine, build_engines, engine_options

CLOSED_DB = "Cannot operate on a closed database."  # what sqlite3 raises; SQLAlchemy classes it as a disconnect


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@dataclass
class Counter:
    n: int = 0


@dataclass
class Statements:
    """Every statement either engine sent, as ``(engine role, first word)``."""

    seen: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.seen)

    def by(self, role: str) -> list[str]:
        return [word for who, word in self.seen if who == role]


def count_statements(handle: IncidentDB) -> Statements:
    """Listen on *both* engines: reads and writes are separate pools with separate event streams."""
    statements = Statements()
    for role, engine in (("write", handle.engine), ("read", handle.read_engine)):
        if role == "read" and engine is handle.engine:
            continue
        event.listen(
            engine,
            "before_cursor_execute",
            lambda conn, cur, stmt, *_, role=role: statements.seen.append((role, stmt.split()[0].upper())),
        )
    return statements


def count_connects(handle: IncidentDB) -> Counter:
    counter = Counter()
    for engine in handle.engines:
        event.listen(engine, "connect", lambda *_a: setattr(counter, "n", counter.n + 1))
    return counter


@pytest.fixture
def one_conn_db(tmp_path) -> IncidentDB:
    """One connection per pool, so 'the pooled connection' is unambiguous."""
    handle = IncidentDB.from_dsn(f"sqlite:///{tmp_path / 'pool1.db'}", pool_size=1, max_overflow=0)
    handle.init_schema()
    return handle


def drop_idle_connections(handle: IncidentDB, *, only: Engine | None = None) -> None:
    """Kill pooled connections behind the pool's back (server restart / idle timeout)."""
    for engine in handle.engines:
        if only is not None and engine is not only:
            continue
        pooled = engine.raw_connection()
        driver_connection = pooled.driver_connection
        pooled.close()  # back in the pool, still looking healthy
        driver_connection.close()  # now dead


class FakeClock:
    def __init__(self) -> None:
        self.now = time.monotonic()  # answers recorded before the test (fixtures) count as "just now"

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(db_connection, "_monotonic", fake)
    return fake


def fail_every_execute_as_dropped(handle: IncidentDB, monkeypatch) -> Counter:
    """The database is really gone: every statement, on either engine, dies with a disconnect-class error."""
    attempts = Counter()

    def dead(cursor, statement, parameters, context):
        attempts.n += 1
        raise sqlite3.ProgrammingError(CLOSED_DB)

    for engine in handle.engines:
        monkeypatch.setattr(engine.dialect, "do_execute", dead)
        monkeypatch.setattr(engine.dialect, "do_execute_no_params", dead)
    return attempts


def die_on_commit(handle: IncidentDB, monkeypatch) -> None:
    """The connection is lost while COMMIT is in flight: the transaction's outcome is unknown."""

    def dying_commit(_dbapi_connection):
        raise sqlite3.ProgrammingError(CLOSED_DB)

    monkeypatch.setattr(handle.engine.dialect, "do_commit", dying_commit)


def replay_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "replaying" in r.getMessage()]


# --------------------------------------------------------------------------- #
# engine construction
# --------------------------------------------------------------------------- #
PG = make_url("postgresql+psycopg2://u:p@db.example.com:5432/postgres?sslmode=require")


def test_postgres_engines_drop_pre_ping_and_add_liveness_settings():
    writer, reader = engine_options(PG), engine_options(PG, read_only=True)
    for options in (writer, reader):
        assert options["pool_pre_ping"] is False
        assert options["pool_recycle"] == config.DEFAULT_DB_POOL_RECYCLE_SECONDS
        assert options["connect_args"] == {
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
            "tcp_user_timeout": 30_000,
        }
    assert "isolation_level" not in writer  # the transactional engine is never AUTOCOMMIT
    assert reader["isolation_level"] == "AUTOCOMMIT"
    assert (writer["pool_size"], writer["max_overflow"]) == (1, 2)  # writes are rare
    assert (reader["pool_size"], reader["max_overflow"]) == (2, 3)


def test_settings_already_in_the_dsn_are_not_overridden():
    url = make_url("postgresql+psycopg2://u:p@h/db?keepalives_idle=5&connect_timeout=3&sslmode=require")
    connect_args = engine_options(url)["connect_args"]
    assert "keepalives_idle" not in connect_args
    assert "connect_timeout" not in connect_args
    assert connect_args["keepalives_interval"] == 10  # only what the DSN leaves unset is defaulted


def test_pool_recycle_follows_the_environment(monkeypatch):
    monkeypatch.setenv("INCIDENT_DB_POOL_RECYCLE_SECONDS", "120")
    assert engine_options(make_url("postgresql+psycopg2://u:p@h/db"))["pool_recycle"] == 120


def test_sqlite_gets_no_pool_or_libpq_settings():
    assert set(engine_options(make_url("sqlite:///x.db"))) == {"future", "pool_pre_ping"}
    assert set(engine_options(make_url("sqlite:///x.db"), read_only=True)) == {
        "future",
        "pool_pre_ping",
        "isolation_level",
    }


def test_built_postgres_engines_are_separate_and_have_no_pre_ping():
    engine, read_engine = build_engines(make_url("postgresql+psycopg2://u:p@127.0.0.1:1/db"))  # never connects
    assert engine is not read_engine
    assert engine.pool is not read_engine.pool  # its own pool: the only way AUTOCOMMIT costs one round trip
    for built in (engine, read_engine):
        assert built.pool._pre_ping is False  # a ping per checkout is one extra round trip per query
        assert built.pool._recycle == config.DEFAULT_DB_POOL_RECYCLE_SECONDS


def test_in_memory_sqlite_uses_one_engine_for_both_roles():
    """Each connection to ``sqlite://`` is its own empty database, so a second engine could not see the first's data."""
    engine, read_engine = build_engines(make_url("sqlite://"))
    assert engine is read_engine


def test_caller_overrides_win_for_both_engines():
    engine, read_engine = build_engines(make_url("sqlite:///x.db"), pool_pre_ping=True)
    assert engine.pool._pre_ping is True
    assert read_engine.pool._pre_ping is True


def test_a_plain_engine_serves_both_roles_when_no_read_engine_is_given(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plain.db'}")
    handle = IncidentDB(engine)
    assert handle.read_engine is engine
    assert handle.engines == (engine,)


# --------------------------------------------------------------------------- #
# reads on the AUTOCOMMIT read engine, writes in native transactions
# --------------------------------------------------------------------------- #
def test_reads_use_the_read_engine_and_writes_use_the_transactional_one(incident_db):
    statements = count_statements(incident_db)

    incident_db.list_videos()
    assert statements.by("read") == ["SELECT"]
    assert statements.by("write") == []

    incident_db.update_video("nobody", filepath="x.mp4")
    assert statements.by("write") == ["UPDATE"]
    assert statements.by("read") == ["SELECT"]  # unchanged


def test_the_read_engine_is_autocommit_and_the_transactional_engine_is_not(incident_db):
    def autocommit(engine) -> bool:
        with engine.connect() as conn:
            return conn.connection.driver_connection.isolation_level is None  # sqlite3's autocommit mode

    assert autocommit(incident_db.read_engine)
    assert not autocommit(incident_db.engine)  # AUTOCOMMIT is not atomic: never global


def test_a_failed_write_block_rolls_back_every_statement(incident_db):
    with pytest.raises(RuntimeError), incident_db.engine.begin() as conn:
        conn.execute(videos.insert().values(id="A", filepath="a.mp4"))
        conn.execute(videos.insert().values(id="B", filepath="b.mp4"))
        raise RuntimeError("boom")
    assert incident_db.list_videos() == []  # neither insert survived


def test_a_successful_write_block_commits_and_the_read_engine_sees_it(incident_db):
    incident_db.upsert_video("A", filepath="a.mp4")
    assert [v["id"] for v in incident_db.list_videos()] == ["A"]


@pytest.mark.parametrize(
    "statement",
    [
        "insert into videos (id) values ('X')",
        "  UPDATE videos SET filepath = 'x'",
        "delete from videos",
        "create table t (a int)",
        "drop table videos",
        "with gone as (delete from videos returning id) select * from gone",
    ],
)
def test_the_read_engine_refuses_writes(incident_db, statement):
    incident_db.upsert_video("A", filepath="a.mp4")
    with pytest.raises(WriteOnReadEngine), incident_db.read_engine.connect() as conn:
        conn.execute(text(statement))
    assert [v["id"] for v in incident_db.list_videos()] == ["A"]  # nothing was changed


@pytest.mark.parametrize(
    "statement",
    [
        "select 1",
        "  SELECT * FROM videos",
        "with recent as (select id from videos) select * from recent",
        "select count(*) from videos where id = 'updated'",  # the word inside a literal is not a write
        "pragma table_info(videos)",
    ],
)
def test_the_read_engine_allows_reads(incident_db, statement):
    with incident_db.read_engine.connect() as conn:
        conn.execute(text(statement)).all()


def test_the_read_engine_also_refuses_a_core_insert(incident_db):
    with pytest.raises(WriteOnReadEngine), incident_db.read_engine.connect() as conn:
        conn.execute(insert(videos).values(id="A"))


# --------------------------------------------------------------------------- #
# a dropped pooled connection is replayed once, transparently
# --------------------------------------------------------------------------- #
def test_a_dropped_connection_does_not_surface_on_a_read(one_conn_db, caplog):
    one_conn_db.upsert_video("V1", filepath="a.mp4", duration=3)
    connects = count_connects(one_conn_db)
    drop_idle_connections(one_conn_db, only=one_conn_db.read_engine)

    with caplog.at_level(logging.WARNING, logger="db_connection"):
        row = one_conn_db.get_video("V1")

    assert row["filepath"] == "a.mp4"
    assert connects.n == 1  # exactly one fresh connection was opened
    assert len(replay_warnings(caplog)) == 1


def test_a_dropped_connection_does_not_surface_on_a_write_and_applies_once(one_conn_db):
    one_conn_db.upsert_video("V1", filepath="a.mp4")
    drop_idle_connections(one_conn_db, only=one_conn_db.engine)

    one_conn_db.update_video("V1", filepath="b.mp4")

    assert one_conn_db.get_video("V1")["filepath"] == "b.mp4"
    assert len(one_conn_db.list_videos()) == 1


def test_a_call_that_reads_then_writes_survives_both_pools_being_dropped(one_conn_db, caplog):
    """``upsert_video`` reads (read engine) then writes (transactional engine); both pools' connections are stale.

    One replay covers it: when one pool detects the loss the other's idle connections are dropped as well.
    """
    drop_idle_connections(one_conn_db)  # both pools
    with caplog.at_level(logging.WARNING, logger="db_connection"):
        one_conn_db.upsert_video("V2", filepath="x.mp4")
    assert one_conn_db.get_video("V2")["filepath"] == "x.mp4"
    assert replay_warnings(caplog) == [
        "database connection was dropped (ProgrammingError); replaying IncidentDB.upsert_video once on a new connection"
    ]


def test_the_other_pool_is_dropped_when_one_detects_a_lost_connection(one_conn_db, monkeypatch):
    disposed = Counter()
    real_dispose = one_conn_db.engine.dispose

    def spy(*args, **kwargs):
        disposed.n += 1
        return real_dispose(*args, **kwargs)

    monkeypatch.setattr(one_conn_db.engine, "dispose", spy)
    drop_idle_connections(one_conn_db, only=one_conn_db.read_engine)

    one_conn_db.list_videos()  # the read engine loses its connection...

    assert disposed.n == 1  # ...so the transactional engine's idle connections are dropped too


def test_the_replay_is_a_single_retry_not_a_loop(one_conn_db, monkeypatch):
    """The database is really down: the second attempt fails too and that error is what the caller sees."""
    attempts = fail_every_execute_as_dropped(one_conn_db, monkeypatch)
    with pytest.raises(sa_exc.DBAPIError) as caught:
        one_conn_db.get_video("V1")
    assert caught.value.connection_invalidated
    assert attempts.n == 2  # original + exactly one replay


def test_no_replay_once_a_commit_was_attempted(one_conn_db, monkeypatch, caplog):
    """A COMMIT that dies mid-flight has an unknown outcome; replaying could apply the write twice."""
    statements = count_statements(one_conn_db)
    die_on_commit(one_conn_db, monkeypatch)

    with caplog.at_level(logging.WARNING, logger="db_connection"), pytest.raises(sa_exc.DBAPIError) as caught:
        one_conn_db.upsert_video("V1", filepath="a.mp4")

    assert caught.value.connection_invalidated
    assert statements.by("write").count("INSERT") == 1  # the write was not run a second time
    assert not replay_warnings(caplog)
    monkeypatch.undo()
    assert one_conn_db.get_video("V1") == {}  # the unconfirmed transaction never committed here


def test_errors_that_are_not_a_lost_connection_are_never_replayed(one_conn_db, caplog):
    one_conn_db.upsert_video("V1", filepath="a.mp4")
    one_conn_db.insert_model_run("MR", model_name="m")
    one_conn_db.insert_incident("V1", "MR", fields={"type": "burglary"})
    one_conn_db.add_incident_entity("V1", "MR", entity_id="E1")
    statements = count_statements(one_conn_db)

    with caplog.at_level(logging.WARNING, logger="db_connection"), pytest.raises(sa_exc.IntegrityError):
        one_conn_db.add_incident_entity("V1", "MR", entity_id="E1")  # duplicate primary key

    assert statements.by("write").count("INSERT") == 1  # attempted once, not replayed
    assert not replay_warnings(caplog)


def test_every_public_method_is_covered_by_the_replay():
    """New ``IncidentDB`` methods are wrapped automatically; only these two, which manage errors themselves, are not."""
    unwrapped = {
        name
        for name, member in vars(IncidentDB).items()
        if not name.startswith("_") and inspect.isfunction(member) and not hasattr(member, "__wrapped__")
    }
    assert unwrapped == {"healthcheck", "dispose"}


# --------------------------------------------------------------------------- #
# health check: cached while the database is answering, prompt when it is not
# --------------------------------------------------------------------------- #
def test_healthcheck_trusts_a_recent_answer_instead_of_probing(incident_db, clock):
    statements = count_statements(incident_db)

    # init_schema() has just been answered, so a fresh handle needs no probe at all...
    assert incident_db.healthcheck(max_age=15) == (True, "ok")
    assert statements.n == 0

    clock.advance(16)  # ...until that answer is older than the TTL
    assert incident_db.healthcheck(max_age=15) == (True, "ok")
    assert statements.by("read") == ["SELECT"]  # the probe is one autocommit statement on the read engine
    assert incident_db.healthcheck(max_age=15) == (True, "ok")  # and the probe's own answer is trusted in turn
    assert statements.n == 1

    clock.advance(16)
    assert incident_db.healthcheck(max_age=15) == (True, "ok")
    assert statements.n == 2


def test_healthcheck_without_a_ttl_always_probes(incident_db, clock):
    statements = count_statements(incident_db)
    incident_db.healthcheck()
    incident_db.healthcheck()
    incident_db.healthcheck(max_age=0)
    assert statements.n == 3


def test_any_answered_query_counts_as_proof_the_database_is_up(incident_db, clock):
    incident_db.list_videos()
    statements = count_statements(incident_db)
    assert incident_db.healthcheck(max_age=15) == (True, "ok")
    assert statements.n == 0


def test_a_failed_probe_is_reported_at_once_and_never_cached(incident_db, clock, monkeypatch):
    def refused():
        raise sa_exc.OperationalError("SELECT 1", {}, Exception("connection refused"))

    clock.advance(16)  # the earlier answer is stale, so the probe runs
    monkeypatch.setattr(incident_db, "_ping", refused)
    ok, detail = incident_db.healthcheck(max_age=15)
    assert not ok
    assert "connection refused" in detail

    monkeypatch.undo()  # the database is back: the very next call sees it, no negative caching
    assert incident_db.healthcheck(max_age=15) == (True, "ok")


def test_a_connection_error_ends_the_cached_answer_early(incident_db, clock, monkeypatch):
    incident_db.list_videos()
    assert incident_db.healthcheck(max_age=15) == (True, "ok")  # cached: nothing to probe
    statements = count_statements(incident_db)

    # The database goes away inside the TTL: a COMMIT fails with a disconnect (which is not replayed)...
    die_on_commit(incident_db, monkeypatch)
    with pytest.raises(sa_exc.DBAPIError):
        incident_db.upsert_video("V1", filepath="a.mp4")
    monkeypatch.undo()

    # ...so the next health check must not trust the earlier answer.
    before = statements.n
    incident_db.healthcheck(max_age=15)
    assert statements.n == before + 1


# --------------------------------------------------------------------------- #
# ui.get_db_or_notice: the per-page-run entry point
# --------------------------------------------------------------------------- #
@pytest.fixture
def served_db(incident_db, monkeypatch):
    monkeypatch.setattr("db.is_configured", lambda: True)
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    return incident_db


def test_page_runs_within_the_ttl_send_one_probe_between_them(served_db, clock):
    clock.advance(16)  # the start-up answer is stale: the first page run probes, the rest ride on it
    statements = count_statements(served_db)
    for _ in range(5):
        assert ui.get_db_or_notice() is served_db
    assert statements.n == 1


def test_a_page_run_right_after_start_up_needs_no_probe(served_db):
    statements = count_statements(served_db)
    assert ui.get_db_or_notice() is served_db
    assert statements.n == 0  # get_db() just ran init_schema() against the database


def test_ttl_zero_probes_every_page_run(served_db, monkeypatch):
    monkeypatch.setenv("INCIDENT_DB_HEALTHCHECK_TTL_SECONDS", "0")
    statements = count_statements(served_db)
    for _ in range(3):
        ui.get_db_or_notice()
    assert statements.n == 3


NOTICE_SCRIPT = """
import streamlit as st
from ui import get_db_or_notice

handle = get_db_or_notice()
st.write("HANDLE" if handle is not None else "NO HANDLE")
"""


def test_unreachable_database_shows_the_notice(served_db, clock, monkeypatch):
    clock.advance(16)  # a stale answer forces the probe

    def refused():
        raise sa_exc.OperationalError("SELECT 1", {}, Exception("could not connect to server"))

    monkeypatch.setattr(served_db, "_ping", refused)
    app = AppTest.from_string(NOTICE_SCRIPT, default_timeout=15).run()
    assert not app.exception
    assert any("Database configured but unreachable" in m.value for m in app.markdown)
    assert any(m.value == "NO HANDLE" for m in app.markdown)


def test_an_outage_inside_the_ttl_shows_the_notice_on_the_next_run(served_db, monkeypatch):
    """Cached 'healthy' can send at most one page run into a query error; the run after that shows the notice."""
    served_db.upsert_video("V1", filepath="a.mp4")
    assert ui.get_db_or_notice() is served_db  # healthy, and now cached

    attempts = fail_every_execute_as_dropped(served_db, monkeypatch)
    assert ui.get_db_or_notice() is served_db  # inside the TTL: no probe, so this run trusts the cache...
    assert attempts.n == 0
    with pytest.raises(sa_exc.DBAPIError):
        served_db.get_video("V1")  # ...and its own query hits the outage (after the single replay)

    app = AppTest.from_string(NOTICE_SCRIPT, default_timeout=15).run()  # the next run
    assert any("Database configured but unreachable" in m.value for m in app.markdown)


# --------------------------------------------------------------------------- #
# settings and start-up
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 15.0), ("30", 30.0), ("0", 0.0), ("2.5", 2.5), ("-4", 0.0), ("soon", 15.0), ("", 15.0)],
)
def test_healthcheck_ttl_setting(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("INCIDENT_DB_HEALTHCHECK_TTL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("INCIDENT_DB_HEALTHCHECK_TTL_SECONDS", raw)
    assert config.db_healthcheck_ttl_seconds() == expected


@pytest.mark.parametrize(("raw", "expected"), [(None, 600), ("60", 60), ("-1", -1), ("x", 600)])
def test_pool_recycle_setting(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("INCIDENT_DB_POOL_RECYCLE_SECONDS", raising=False)
    else:
        monkeypatch.setenv("INCIDENT_DB_POOL_RECYCLE_SECONDS", raw)
    assert config.db_pool_recycle_seconds() == expected


def test_init_schema_costs_one_catalog_query_when_everything_exists(incident_db):
    statements = count_statements(incident_db)
    incident_db.init_schema()
    incident_db.init_schema()
    # create_all(checkfirst=True) alone would be one existence query per table, every time.
    assert statements.by("read") == ["SELECT", "SELECT"]
    assert statements.by("write") == []
    assert len(metadata.tables) > 10


def test_init_schema_creates_only_what_is_missing(tmp_path):
    handle = IncidentDB.from_dsn(f"sqlite:///{tmp_path / 'partial.db'}")
    videos.create(handle.engine)  # a database that already has one table
    handle.init_schema()
    assert set(db_connection.sa_inspect(handle.read_engine).get_table_names()) == set(metadata.tables)


def test_a_failed_start_up_disposes_the_half_built_engines(monkeypatch, tmp_path):
    monkeypatch.setattr("config.incident_db_dsn", lambda: f"sqlite:///{tmp_path / 'x.db'}")
    monkeypatch.setattr(IncidentDB, "init_schema", lambda self: (_ for _ in ()).throw(RuntimeError("no schema")))
    disposed = Counter()
    real_dispose = Engine.dispose

    def spy(self, *args, **kwargs):
        disposed.n += 1
        return real_dispose(self, *args, **kwargs)

    monkeypatch.setattr(Engine, "dispose", spy)

    assert db.get_db() is None
    assert disposed.n == 2  # the transactional engine and the read engine
