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

"""Connection-layer behaviour behind :class:`db.IncidentDB`: round trips and dropped connections.

The database is remote, so every network round trip costs the full RTT, and the old
engine settings paid for four of them per query (measured on real PostgreSQL behind a
latency proxy, see ``scripts/measure_db_roundtrips.py``): the ``pool_pre_ping``
``SELECT 1``, psycopg2's implicit ``BEGIN``, the statement, and the pool's ``ROLLBACK``
on return. This module removes the avoidable three:

* **No pre-ping.** A pooled connection is trusted, aged out with ``pool_recycle`` and kept
  alive with TCP keepalives; nothing is sent to validate it at checkout.
* **Two engines, never a global AUTOCOMMIT.** ``IncidentDB.engine`` is the ordinary
  transactional engine: writes use ``engine.begin()`` and get native SQLAlchemy
  transactions. ``IncidentDB.read_engine`` is a *separate*, dedicated AUTOCOMMIT engine
  with its own pool, used by read-only code: no ``BEGIN``, no ``ROLLBACK``, one round trip
  per statement. AUTOCOMMIT is not atomic, so the read engine refuses write statements
  (:class:`WriteOnReadEngine`). It needs its own pool: switching the level per checkout
  (``execution_options`` on a shared pool) costs two round trips per read, because SQLAlchemy
  resets the isolation level on every return to the pool and psycopg2 then sends a ``SET``.
* **A dropped connection is replayed, once.** Without pre-ping a stale pooled connection is
  only discovered by the statement that uses it. SQLAlchemy then invalidates that pool and
  raises; :func:`replay_on_disconnect` catches it at the public ``IncidentDB`` method and
  runs the whole call again on a fresh connection (SQLAlchemy's documented approach: retry
  the entire operation from the start of the transaction). A dropped connection rolls the
  server-side transaction back, so replaying is safe **unless a COMMIT was attempted** (its
  outcome is unknown): then the error is raised. Errors that are not a lost connection are
  never replayed. Both pools sit behind the same network path, so when one detects a loss
  the other's idle connections are dropped too, and one replay covers a call that reads
  and then writes.

:class:`ConnectionGuard` also remembers when the database last answered so
``healthcheck(max_age=...)`` can skip its probe.
"""

from __future__ import annotations

import functools
import inspect
import logging
import re
import threading
import time
from collections.abc import Callable, Collection
from typing import Any, TypeVar

from sqlalchemy import MetaData, Table, event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import URL, Connection, Engine, create_engine
from sqlalchemy.exc import DBAPIError

import config

log = logging.getLogger(__name__)
_monotonic = time.monotonic  # tests replace this alias, never time.monotonic itself

T = TypeVar("T")

# libpq connection parameters, https://www.postgresql.org/docs/current/libpq-connect.html
# Set only when the DSN does not already carry them, so the DSN stays the place to override.
_LIBPQ_DEFAULTS: dict[str, int] = {
    # libpq waits indefinitely without this; a black-holed host would freeze a page for the
    # OS SYN-retry window instead of showing the "unreachable" notice.
    "connect_timeout": 10,
    # OS default keepalive idle time is 2 h on Linux: far too long to keep a NAT/firewall
    # mapping alive or to notice a dead peer. Dead-peer detection: 30 + 3 x 10 = 60 s idle.
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    # Keepalives only run on an idle socket; this bounds data sent but never acknowledged
    # (a query on a black-holed connection), which otherwise waits for TCP's ~15 min give-up.
    "tcp_user_timeout": 30_000,  # milliseconds
}
_LIBPQ_DRIVERS = {"psycopg2", "psycopg"}


def engine_options(url: URL, *, read_only: bool = False) -> dict[str, Any]:
    """``create_engine`` keyword arguments for the transactional engine, or the read-only one (AUTOCOMMIT)."""
    options: dict[str, Any] = {"future": True, "pool_pre_ping": False}
    if read_only:
        options["isolation_level"] = "AUTOCOMMIT"
    if url.get_backend_name() == "sqlite":
        return options
    # Small app-side pools: the Supabase pooler (Supavisor) does the real pooling server-side, and in
    # session mode every pooled connection holds a pooler slot. Writes are rare, so their pool is smaller.
    options.update(
        pool_size=2 if read_only else 1,
        max_overflow=3 if read_only else 2,
        pool_recycle=config.db_pool_recycle_seconds(),
    )
    if url.get_backend_name() == "postgresql" and url.get_driver_name() in _LIBPQ_DRIVERS:
        options["connect_args"] = {k: v for k, v in _LIBPQ_DEFAULTS.items() if k not in url.query}
    return options


# --------------------------------------------------------------------------- #
# The read-only engine
# --------------------------------------------------------------------------- #
class WriteOnReadEngine(RuntimeError):
    """A write statement was sent to the AUTOCOMMIT read engine, where it could not be atomic."""


_WRITE_START = re.compile(
    r"^\s*(?:insert|update|delete|merge|truncate|create|alter|drop|grant|revoke|copy|vacuum|reindex|lock|call|do)\b",
    re.IGNORECASE,
)
_WRITE_IN_CTE = re.compile(r"\b(?:insert|update|delete|merge)\b", re.IGNORECASE)


def _refuse_writes(_conn: Connection, _cursor: Any, statement: str, *_rest: Any) -> None:
    if _WRITE_START.match(statement) or (statement.lstrip()[:4].lower() == "with" and _WRITE_IN_CTE.search(statement)):
        raise WriteOnReadEngine(
            "refused a write on the read-only AUTOCOMMIT engine (not atomic): use engine.begin() for writes"
        )


def build_engines(url: URL, **overrides: Any) -> tuple[Engine, Engine]:
    """``(engine, read_engine)`` for ``url``; ``overrides`` (from ``from_dsn``) win for both.

    An in-memory SQLite database exists per connection, so there a second engine would see a
    different (empty) database: the one engine serves both roles.
    """
    engine = create_engine(url, **{**engine_options(url), **overrides})
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        return engine, engine
    read_engine = create_engine(url, **{**engine_options(url, read_only=True), **overrides})
    event.listen(read_engine, "before_cursor_execute", _refuse_writes)
    return engine, read_engine


def missing_tables(engine: Engine, metadata: MetaData) -> list[Table]:
    """Tables of ``metadata`` absent from the database, from one catalog query.

    ``MetaData.create_all(checkfirst=True)`` issues one existence query per table
    (18 round trips on a database that is already set up, on every process start).
    """
    existing = set(sa_inspect(engine).get_table_names())
    return [table for table in metadata.sorted_tables if table.name not in existing]


# --------------------------------------------------------------------------- #
# Liveness + replay after a dropped connection
# --------------------------------------------------------------------------- #
class ConnectionGuard:
    """Bookkeeping over the engine(s): when the database last answered, and one replay after a lost connection."""

    def __init__(self, *engines: Engine) -> None:
        self.last_ok: float | None = None  # monotonic time of the last statement the database answered
        self._local = threading.local()  # per thread: is a public call running, did it attempt a COMMIT
        self._engines = tuple({id(e): e for e in engines}.values())
        self._operational_error = self._engines[0].dialect.loaded_dbapi.OperationalError
        for engine in self._engines:
            event.listen(engine, "after_cursor_execute", self._statement_answered)
            event.listen(engine, "commit", self._commit_attempted)
            event.listen(engine, "handle_error", self._statement_failed)

    # -- engine events -------------------------------------------------------- #
    def _statement_answered(self, *_args: Any, **_kwargs: Any) -> None:
        self.last_ok = _monotonic()

    def _commit_attempted(self, _conn: Connection) -> None:
        self._local.committed = True  # fires *before* the DBAPI commit, so a failing COMMIT counts

    def _statement_failed(self, context: Any) -> None:
        if context.is_disconnect or isinstance(context.original_exception, self._operational_error):
            self.last_ok = None
        if context.is_disconnect:
            # The other pool's idle connections crossed the same network path; do not make the
            # replay discover them one failure at a time.
            for other in self._engines:
                if other is not context.engine:
                    other.dispose()

    # -- liveness ------------------------------------------------------------- #
    def answered_within(self, max_age: float) -> bool:
        last = self.last_ok
        return max_age > 0 and last is not None and _monotonic() - last < max_age

    # -- replay --------------------------------------------------------------- #
    def run(self, call: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run ``call``; if its connection was lost before any COMMIT was attempted, run it once more."""
        state = self._local
        if getattr(state, "active", False):  # a public method calling another: the outermost call decides
            return call(*args, **kwargs)
        state.active, state.committed = True, False
        try:
            try:
                return call(*args, **kwargs)
            except DBAPIError as exc:
                if not exc.connection_invalidated or state.committed:
                    raise
                log.warning(
                    "database connection was dropped (%s); replaying %s once on a new connection",
                    type(exc.orig).__name__,
                    getattr(call, "__qualname__", call),
                )
            state.committed = False
            return call(*args, **kwargs)
        finally:
            state.active = False


def replay_on_disconnect(*, skip: Collection[str] = ()) -> Callable[[type[T]], type[T]]:
    """Class decorator: route every public method through ``self._guard.run`` (so new methods are covered too)."""

    def wrap(method: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(method)
        def replayed(self: Any, *args: Any, **kwargs: Any) -> Any:
            return self._guard.run(method, self, *args, **kwargs)

        return replayed

    def decorate(cls: type[T]) -> type[T]:
        for name, member in list(vars(cls).items()):
            if not name.startswith("_") and name not in skip and inspect.isfunction(member):
                setattr(cls, name, wrap(member))
        return cls

    return decorate
