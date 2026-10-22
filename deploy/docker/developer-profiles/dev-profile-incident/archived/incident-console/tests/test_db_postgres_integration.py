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

"""The DB layer against a real PostgreSQL 16 (optional; skipped unless ``pgserver`` is installed).

    uv run --with pgserver python -m pytest tests/test_db_postgres_integration.py

``pgserver`` is a wheel that bundles a disposable Postgres, so nothing is installed system-wide
and no credentials are involved. What SQLite cannot show is checked here: psycopg2's real error
strings meeting SQLAlchemy's disconnect classification and the replay, the wire round trips per
statement, and the libpq keepalive settings reaching the socket. The measured latency numbers
come from ``scripts/measure_db_roundtrips.py``.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pgserver = pytest.importorskip("pgserver", reason="optional: uv run --with pgserver python -m pytest <this file>")

from sqlalchemy import create_engine, text  # noqa: E402

from db import IncidentDB, videos  # noqa: E402
from db_connection import WriteOnReadEngine  # noqa: E402
from scripts.latency_proxy import LatencyProxy  # noqa: E402

APP_NAME = "incident-console-pgtest"


@pytest.fixture(scope="module")
def sockdir(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="stop")
    yield server.get_uri().split("host=")[-1]
    server.cleanup()


@pytest.fixture
def control(sockdir):
    engine = create_engine(
        f"postgresql+psycopg2://postgres@/postgres?host={sockdir}&application_name=incident-control",
        isolation_level="AUTOCOMMIT",
    )
    yield engine
    engine.dispose()


@pytest.fixture
def pg(sockdir, control):
    """(handle, proxy, kill): an IncidentDB talking to Postgres through a round-trip-counting proxy."""
    proxy = LatencyProxy(f"{sockdir}/.s.PGSQL.5432")
    dsn = f"postgresql+psycopg2://postgres@127.0.0.1:{proxy.port}/postgres?sslmode=disable&application_name={APP_NAME}"
    handle = IncidentDB.from_dsn(dsn)
    handle.init_schema()
    with control.connect() as conn:
        conn.execute(text("delete from videos"))

    def kill() -> None:
        """What a pooler restart or an idle timeout looks like to the client: its backend disappears."""
        with control.connect() as conn:
            conn.execute(
                text("select pg_terminate_backend(pid) from pg_stat_activity where application_name = :n"),
                {"n": APP_NAME},
            )
        time.sleep(0.2)

    yield handle, proxy, kill
    handle.dispose()
    proxy.close()


def round_trips(proxy: LatencyProxy, fn) -> int:
    before = proxy.round_trips
    fn()
    return proxy.round_trips - before


def test_a_read_is_one_round_trip_and_a_write_is_its_statements_plus_two(pg):
    handle, proxy, _ = pg
    handle.upsert_video("V1", filepath="a.mp4")
    handle.list_videos()  # connection is open and warm

    assert round_trips(proxy, lambda: handle.get_video("V1")) == 1  # was 4: ping + BEGIN + SELECT + ROLLBACK
    assert round_trips(proxy, handle.healthcheck) == 1
    assert round_trips(proxy, lambda: handle.update_video("V1", filepath="b.mp4")) == 3  # BEGIN, UPDATE, COMMIT


def test_a_page_run_after_a_recent_answer_sends_nothing(pg):
    handle, proxy, _ = pg
    handle.list_videos()
    assert round_trips(proxy, lambda: handle.healthcheck(max_age=15)) == 0


def test_a_write_block_is_atomic_on_postgres(pg):
    handle, _, _ = pg
    with pytest.raises(RuntimeError), handle.engine.begin() as conn:
        conn.execute(videos.insert().values(id="A", filepath="a.mp4"))
        conn.execute(videos.insert().values(id="B", filepath="b.mp4"))
        raise RuntimeError("boom")
    assert handle.list_videos() == []  # both inserts rolled back together

    with handle.engine.begin() as conn:
        conn.execute(videos.insert().values(id="A", filepath="a.mp4"))
        conn.execute(videos.insert().values(id="B", filepath="b.mp4"))
    assert [v["id"] for v in handle.list_videos()] == ["A", "B"]


def replayed_calls(caplog) -> list[str]:
    return [
        m.split("replaying ")[1].split(" once")[0] for m in (r.getMessage() for r in caplog.records) if "replaying" in m
    ]


def test_a_killed_backend_is_replayed_once_per_kill_for_reads_and_for_writes(pg, caplog):
    handle, _, kill = pg
    handle.upsert_video("V1", filepath="a.mp4")  # a connection is open in each pool

    kill()  # the read engine's backend disappears (idle timeout, pooler restart)
    assert handle.get_video("V1")["filepath"] == "a.mp4"  # no exception reaches the caller
    assert replayed_calls(caplog) == ["IncidentDB.get_video"]

    handle.upsert_video("V1", filepath="b.mp4")  # both pools have live connections again
    kill()  # this time a write is the first call to find its connection dead
    handle.update_video("V1", filepath="c.mp4")  # nothing was applied when it failed, so it is safe to replay
    assert handle.get_video("V1")["filepath"] == "c.mp4"  # the read pool was refreshed by that same failure
    assert replayed_calls(caplog) == ["IncidentDB.get_video", "IncidentDB.update_video"]  # one replay per kill


def test_one_replay_covers_a_call_that_reads_then_writes_when_both_pools_are_stale(pg):
    """``upsert_video`` reads (read engine) then writes (transactional engine); every pooled connection is killed."""
    handle, _, kill = pg
    handle.upsert_video("V1", filepath="a.mp4")  # opens a connection in both pools
    first, second = handle.read_engine.connect(), handle.read_engine.connect()  # and a second one on the read pool
    first.close()
    second.close()

    kill()
    handle.upsert_video("V1", filepath="b.mp4")  # one call, one replay, however many connections were stale
    assert handle.get_video("V1")["filepath"] == "b.mp4"


def test_the_read_engine_refuses_writes_on_postgres_too(pg):
    handle, _, _ = pg
    with pytest.raises(WriteOnReadEngine), handle.read_engine.connect() as conn:
        conn.execute(videos.insert().values(id="X", filepath="x.mp4"))
    assert handle.list_videos() == []


def test_libpq_liveness_settings_reach_the_socket_of_both_pools(pg):
    handle, _, _ = pg
    if not hasattr(socket, "TCP_USER_TIMEOUT"):
        pytest.skip("Linux-only socket options")
    handle.upsert_video("V1", filepath="a.mp4")  # make sure the transactional pool has a connection too
    assert len(handle.engines) == 2
    for engine in handle.engines:
        with engine.connect() as conn:
            sock = socket.socket(fileno=os.dup(conn.connection.driver_connection.fileno()))
            with sock:
                assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
                assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == 30
                assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == 10
                assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == 3
                assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == 30_000


def test_connect_timeout_turns_a_silent_server_into_a_prompt_error_and_the_dsn_can_set_it():
    """A server that accepts the TCP connection but never speaks would hang libpq forever without connect_timeout."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    accepted: list[socket.socket] = []
    threading.Thread(target=lambda: accepted.append(listener.accept()[0]), daemon=True).start()
    port = listener.getsockname()[1]

    handle = IncidentDB.from_dsn(f"postgresql+psycopg2://u:p@127.0.0.1:{port}/db?sslmode=disable&connect_timeout=2")
    started = time.perf_counter()
    ok, detail = handle.healthcheck()
    elapsed = time.perf_counter() - started

    assert not ok
    assert "timeout expired" in detail
    assert 1.5 < elapsed < 6  # the DSN's 2 s, not the library default of waiting indefinitely
    listener.close()
    for conn in accepted:
        conn.close()
