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

"""Time the incident console's database path against YOUR real DSN, without leaking it.

    cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
    uv run python scripts/db_timing.py                 # about 10 seconds
    uv run python scripts/db_timing.py --idle 60,300   # also: does an idle connection survive 1 and 5 minutes?

* Reads the DSN exactly as the app does (``INCIDENT_DB_DSN`` from the environment, or the untracked
  ``.env.local`` that ``config.py`` loads). Nothing is written to disk.
* Read-only: it runs ``SELECT`` statements only (``SELECT 1``, plus the app's own incident list query).
* Prints no secrets: never the DSN, host, user, password, database name or IP address, and never a stack
  trace. Errors are reduced to the exception type; ``--show-errors`` adds the message with every one of
  those values (and any IP address) replaced by a placeholder.

It compares the settings the console uses now against the previous ones (``pool_pre_ping`` plus one
transaction per query) over your actual network, and reports each in units of the network round trip
measured by a bare TCP connect, so the numbers are comparable across networks.
"""

from __future__ import annotations

import argparse
import re
import socket
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (loads .env / .env.local exactly as the app does)
from db import IncidentDB  # noqa: E402

PAGE_QUERIES = 40  # a typical Incident Reports page run, for the "what it means" line


def redact(message: str, url: URL) -> str:
    """Replace every identifying part of ``url`` (and any IP address) in ``message``."""
    for value, placeholder in (
        (url.password, "<password>"),
        (url.username, "<user>"),
        (url.host, "<host>"),
        (url.database, "<database>"),
    ):
        if value:
            message = message.replace(str(value), placeholder)
    message = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<ip>", message)
    return re.sub(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{0,4}\b", "<ip>", message)


def describe_endpoint(url: URL) -> str:
    """What kind of endpoint the DSN points at, without naming it."""
    host = url.host or ""
    if host.endswith(".pooler.supabase.com"):
        mode = {5432: "session mode", 6543: "transaction mode"}.get(url.port or 5432, f"port {url.port}")
        return f"Supabase shared pooler (Supavisor), {mode}"
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return "Supabase direct connection"
    return "other host" if host else "no network host (local file or socket)"


def tls_summary(raw: object) -> str:
    info = getattr(raw, "info", None)  # psycopg2 only
    if info is None:
        return "n/a"
    return str(info.ssl_attribute("protocol")) if info.ssl_in_use else "none"


def timed_ms(fn: Callable[[], object], samples: int) -> list[float]:
    out = []
    for _ in range(samples):
        started = time.perf_counter()
        fn()
        out.append((time.perf_counter() - started) * 1000)
    return out


def summary(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    return statistics.median(ordered), ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=15, help="repetitions per measurement (default 15)")
    parser.add_argument("--idle", default="", help="comma-separated seconds an idle connection is held, e.g. 60,300")
    parser.add_argument("--show-errors", action="store_true", help="include redacted error messages")
    args = parser.parse_args(argv)

    dsn = config.incident_db_dsn()
    if not dsn:
        print("INCIDENT_DB_DSN is not set (environment or incident-console/.env.local).", file=sys.stderr)
        return 2
    url = make_url(dsn)

    def fail(what: str, exc: Exception) -> int:
        detail = f": {redact(str(exc).splitlines()[0] if str(exc) else '', url)}" if args.show_errors else ""
        print(f"\n{what} failed ({type(exc).__name__}){detail}", file=sys.stderr)
        return 1

    print(f"endpoint : {describe_endpoint(url)}")
    print(
        f"driver   : {url.drivername}, port {url.port or 'default'}, sslmode={url.query.get('sslmode', 'libpq default')}"
    )

    tcp_ms = None
    if url.host:
        try:
            tcp_ms = timed_ms(lambda: socket.create_connection((url.host, url.port or 5432), timeout=10).close(), 5)
        except OSError as exc:
            return fail("TCP connect", exc)

    current = IncidentDB.from_dsn(dsn)  # the console's own engine settings
    previous = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3, future=True)  # what it used to be

    def select_one(engine) -> Callable[[], object]:
        def run() -> object:
            with engine.connect() as conn:
                return conn.execute(text("select 1")).scalar_one()

        return run

    try:
        started = time.perf_counter()
        with current.read_engine.connect() as conn:
            conn.execute(text("select 1"))
            tls = tls_summary(conn.connection.driver_connection)
        first_ms = (time.perf_counter() - started) * 1000
        select_one(previous)()  # open the old-settings pool's connection too, so only warm queries are timed

        now = timed_ms(select_one(current.read_engine), args.samples)
        before = timed_ms(select_one(previous), args.samples)
    except Exception as exc:  # noqa: BLE001 - reduced to a type name, never a traceback
        return fail("query", exc)

    incidents: list[int] = []
    try:  # the app's own read; skipped, not fatal, when the schema has not been created yet
        listing = timed_ms(lambda: incidents.append(len(current.list_latest_incidents())), max(3, args.samples // 3))
    except Exception as exc:  # noqa: BLE001
        listing = []
        print(f"(incident list query skipped: {type(exc).__name__})", file=sys.stderr)

    floor = statistics.median(tcp_ms) if tcp_ms else None
    rows = [
        ("TCP connect (network round trip)", tcp_ms),
        ("warm SELECT 1, console settings now", now),
        ("warm SELECT 1, previous settings", before),
        (f"incident list query now ({incidents[0]} rows)" if incidents else "incident list query now", listing),
    ]
    print(f"TLS      : {tls}; first connection (TCP + TLS + login + setup): {first_ms:,.0f} ms\n")
    print(f"{'measurement':<42} {'median ms':>10} {'p95 ms':>8} {'x RTT':>7}")
    for label, values in rows:
        if values:
            median, p95 = summary(values)
            ratio = f"{median / floor:.1f}" if floor else "-"
            print(f"{label:<42} {median:>10.0f} {p95:>8.0f} {ratio:>7}")

    per_now, per_before = statistics.median(now), statistics.median(before)
    print(
        f"\n{PAGE_QUERIES} queries: previous settings ~{per_before * PAGE_QUERIES / 1000:.1f} s, "
        f"now ~{per_now * PAGE_QUERIES / 1000:.1f} s (medians above; the health probe adds a "
        f"previous-settings query to every page run and no longer does)."
    )

    seconds = sorted({int(s) for s in args.idle.split(",") if s.strip().isdigit()})[:4]  # the pool holds at most 5
    if seconds:
        print(f"\nidle test: holding {len(seconds)} connection(s), checking each after {seconds} s ...", flush=True)
        held = {s: current.read_engine.raw_connection() for s in seconds}
        started = time.monotonic()
        for s in seconds:
            time.sleep(max(0.0, started + s - time.monotonic()))
            try:
                cursor = held[s].cursor()
                cursor.execute("select 1")
                cursor.close()
                print(f"  idle {s:>5} s: connection alive")
            except Exception as exc:  # noqa: BLE001
                print(f"  idle {s:>5} s: connection DROPPED ({type(exc).__name__})")
        for pooled in held.values():
            pooled.invalidate()
    current.dispose()
    previous.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
