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

"""Measure network round trips per page run and per query, at modelled latency.

Runs the console's real DB layer (``db.py`` and ``ui.get_db_or_notice``) against a
*disposable* PostgreSQL started from the ``pgserver`` wheel, through
``latency_proxy.LatencyProxy``, which counts wire round trips and delays every
message by ``rtt/2`` per direction. No remote database, no credentials.

    uv run --with pgserver python scripts/measure_db_roundtrips.py --rtt-ms 0 30 80
    # measure another checkout of the console instead (e.g. the commit before a change):
    uv run --with pgserver python scripts/measure_db_roundtrips.py --code-dir /path/to/incident-console

What is measured vs. modelled - keep this straight when quoting numbers:

* Measured: SQL statements, pool checkouts, pre-pings and new connections
  (SQLAlchemy events); wire round trips (the proxy); wall-clock at the injected RTT.
* Modelled: the network. The RTT is injected; there is no TLS handshake, no SCRAM
  exchange and no Supavisor hop, so a real remote connection *setup* costs more
  round trips than counted here. Per-query counts are protocol-level and carry over.
* Not measured: anything against the real Supabase project (no credentials here);
  use ``scripts/db_timing.py`` for that.

The harness never reads ``INCIDENT_DB_DSN``: it repoints ``config.incident_db_dsn`` at
its own proxy after import (``config`` loads ``.env.local`` on import) and asserts it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "incident-console-measure"
TTL_ENV = "INCIDENT_DB_HEALTHCHECK_TTL_SECONDS"


def _load_latency_proxy():
    """Load the proxy from *this* checkout by path, so ``--code-dir`` may shadow the ``scripts`` package."""
    spec = importlib.util.spec_from_file_location("latency_proxy", Path(__file__).with_name("latency_proxy.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["latency_proxy"] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Counters:
    """Process-wide SQLAlchemy-event counters (one engine is live at a time in this harness)."""

    statements: int = 0
    checkouts: int = 0
    pings: int = 0
    connects: int = 0

    def snapshot(self) -> tuple[int, int, int, int]:
        return self.statements, self.checkouts, self.pings, self.connects


def install_counters() -> Counters:
    """Count on the ``Engine``/``Pool`` *classes* so engines created later (cold start) are covered."""
    from sqlalchemy import event
    from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import Pool

    counters = Counters()

    def bump(name: str):
        def _inc(*_a, **_k):
            setattr(counters, name, getattr(counters, name) + 1)

        return _inc

    event.listen(Engine, "before_cursor_execute", bump("statements"))
    event.listen(Pool, "checkout", bump("checkouts"))
    event.listen(Pool, "connect", bump("connects"))

    ping = PGDialect_psycopg2.do_ping  # pool_pre_ping's SELECT 1 bypasses cursor events

    def counting_ping(self, dbapi_connection):
        counters.pings += 1
        return ping(self, dbapi_connection)

    PGDialect_psycopg2.do_ping = counting_ping
    return counters


@dataclass
class Result:
    scenario: str
    rtt_ms: float
    statements: int
    checkouts: int
    pings: int
    connects: int
    round_trips: int
    seconds: float
    error: str = ""


@dataclass
class Report:
    code_dir: str
    postgres: str
    results: list[Result] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    health_ttl: (
        str  # INCIDENT_DB_HEALTHCHECK_TTL_SECONDS: "0" = probe every page run; ignored by code without the cache
    )
    run: Callable[[], None]
    warm: Callable[[], None] = lambda: None  # pool connected / health cache primed, before latency is injected
    before: Callable[[], None] = lambda: None  # disturbance applied after warm-up (e.g. kill the backend)
    cold: bool = False  # measure engine construction too (a fresh process)


def _median(results: list[Result]) -> Result:
    """Median wall-clock; counts are deterministic, so the first run's counts are kept."""
    return Result(**{**asdict(results[0]), "seconds": statistics.median(r.seconds for r in results)})


class Harness:
    def __init__(self, *, code_dir: Path, repeat: int, quiet: bool) -> None:
        self.code_dir = code_dir
        self.repeat = repeat
        self.quiet = quiet

    def log(self, message: str) -> None:
        if not self.quiet:
            print(message, file=sys.stderr, flush=True)

    def run(self, rtts: list[float]) -> Report:
        import pgserver

        latency_proxy = _load_latency_proxy()
        os.environ["PGAPPNAME"] = APP_NAME  # tags the app's backends; the control connection overrides it
        sys.path.insert(0, str(self.code_dir))
        os.chdir(self.code_dir)
        from sqlalchemy import create_engine, text

        import config
        import db
        import ui
        from scripts.seed_supabase import seed

        counters = install_counters()

        with tempfile.TemporaryDirectory(prefix="pgmeasure-") as pgdata:
            server = pgserver.get_server(Path(pgdata), cleanup_mode="stop")
            sockdir = server.get_uri().split("host=")[-1]
            control = create_engine(
                f"postgresql+psycopg2://postgres@/postgres?host={sockdir}&application_name=measure-control",
                isolation_level="AUTOCOMMIT",
            )
            with control.connect() as conn:
                version = conn.execute(text("select split_part(version(), ',', 1)")).scalar_one()

            # Seed straight into Postgres (no proxy, no latency): the schema + the 36 fixture incidents.
            direct = db.IncidentDB.from_dsn(f"postgresql+psycopg2://postgres@/postgres?host={sockdir}")
            direct.init_schema()
            seed(direct)
            ids = [row["incident_id"] for row in direct.list_latest_incidents()]
            filepath = direct.get_video(ids[0])["filepath"]  # written back unchanged by the write scenarios
            direct.dispose() if hasattr(direct, "dispose") else direct.engine.dispose()

            proxy = latency_proxy.LatencyProxy(f"{sockdir}/.s.PGSQL.5432")
            dsn = f"postgresql+psycopg2://postgres@127.0.0.1:{proxy.port}/postgres?sslmode=disable"
            config.incident_db_dsn = lambda: dsn  # config loaded .env.local on import: never use its DSN
            assert "127.0.0.1" in config.incident_db_dsn()

            def kill_app_backends() -> None:
                with control.connect() as conn:
                    conn.execute(
                        text(
                            "select pg_terminate_backend(pid) from pg_stat_activity "
                            "where application_name = :name and pid <> pg_backend_pid()"
                        ),
                        {"name": APP_NAME},
                    )
                time.sleep(0.2)

            def page_run() -> None:
                assert ui.get_db_or_notice() is not None

            def page_burst() -> None:
                handle = ui.get_db_or_notice()
                for i in range(10):
                    handle.get_video(ids[i % len(ids)])

            def drop_then_page() -> None:
                handle = ui.get_db_or_notice()
                handle.get_video(ids[0])

            def write() -> None:
                db.get_db().update_video(ids[0], filepath=filepath)

            def page_run_and_a_write() -> None:
                page_run()
                write()  # earlier writes in the session: the transactional pool is open and warm

            def cold_start() -> None:
                handle = ui.get_db_or_notice()
                handle.get_video(ids[0])

            def query(fn: Callable[[db.IncidentDB], object]) -> Callable[[], None]:
                return lambda: fn(db.get_db())

            scenarios = [
                Scenario("page run: get_db_or_notice() [health cache cold]", "0", page_run),
                Scenario("page run: get_db_or_notice() [health cache warm]", "15", page_run, warm=page_run),
                Scenario("query: get_video (1 PK lookup)", "15", query(lambda h: h.get_video(ids[0])), warm=page_run),
                Scenario(
                    "query: list_latest_incidents (join, 36 rows)",
                    "15",
                    query(lambda h: h.list_latest_incidents()),
                    warm=page_run,
                ),
                Scenario(
                    "query: list_notifications",
                    "15",
                    query(lambda h: h.list_notifications(only_unacknowledged=True)),
                    warm=page_run,
                ),
                Scenario("page-like: 1 page run + 10 x get_video", "15", page_burst, warm=page_run),
                Scenario(
                    "write: update_video (1 UPDATE) [transactional pool warm]",
                    "15",
                    write,
                    warm=page_run_and_a_write,
                ),
                Scenario(
                    "write: the process's first write [transactional pool cold]",
                    "15",
                    write,
                    warm=page_run,
                ),
                Scenario(
                    "dropped pooled connection: page run + get_video",
                    "0",
                    drop_then_page,
                    warm=page_run,
                    before=kill_app_backends,
                ),
                Scenario(
                    "dropped pooled connection: write (update_video)",
                    "15",
                    write,
                    warm=page_run_and_a_write,
                    before=kill_app_backends,
                ),
                Scenario("cold start: fresh process, 1 page run + 1 query", "0", cold_start, cold=True),
            ]

            report = Report(code_dir=str(self.code_dir), postgres=version)
            try:
                for rtt in rtts:
                    for scenario in scenarios:
                        os.environ[TTL_ENV] = scenario.health_ttl
                        runs = []
                        for _ in range(self.repeat):
                            proxy.rtt_ms = 0
                            db.reset_cache()
                            if not scenario.cold:
                                assert db.get_db() is not None, "harness database unreachable"
                                scenario.warm()
                                scenario.before()
                            proxy.rtt_ms = rtt
                            runs.append(self._measure(scenario.name, rtt, proxy, counters, scenario.run))
                        report.results.append(_median(runs))
                        self.log(f"  rtt={rtt:>4g} ms  {scenario.name}")
            finally:
                db.reset_cache()
                proxy.close()
                control.dispose()
                server.cleanup()
            return report

    @staticmethod
    def _measure(name: str, rtt: float, proxy, counters: Counters, fn: Callable[[], None]) -> Result:
        before, round_trips = counters.snapshot(), proxy.round_trips
        error = ""
        started = time.perf_counter()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - reported in the table, never hidden
            error = type(exc).__name__
        seconds = time.perf_counter() - started
        deltas = [a - b for a, b in zip(counters.snapshot(), before, strict=True)]
        return Result(name, rtt, *deltas, proxy.round_trips - round_trips, seconds, error)


def render(report: Report, rtts: list[float]) -> str:
    """Markdown table: one row per scenario, wall-clock columns per injected RTT."""
    by_name: dict[str, dict[float, Result]] = {}
    for r in report.results:
        by_name.setdefault(r.scenario, {})[r.rtt_ms] = r
    header = ["scenario", "SQL stmts", "checkouts", "pre-pings", "new conns", "wire RTs"]
    header += [f"ms @ {r:g} ms RTT" for r in rtts]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for name, per_rtt in by_name.items():
        first = per_rtt[rtts[0]]
        cells = [name, *map(str, (first.statements, first.checkouts, first.pings, first.connects, first.round_trips))]
        for rtt in rtts:
            r = per_rtt[rtt]
            cells.append(f"{r.seconds * 1000:,.0f}" + (f" ({r.error})" if r.error else ""))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rtt-ms", type=float, nargs="+", default=[0.0, 30.0, 80.0], help="injected round-trip times")
    parser.add_argument("--repeat", type=int, default=3, help="runs per scenario (median wall-clock is reported)")
    parser.add_argument(
        "--code-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="incident-console checkout to measure (default: this one)",
    )
    parser.add_argument("--json", type=Path, help="also write the raw results here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if not (args.code_dir / "db.py").is_file():
        parser.error(f"{args.code_dir} does not look like an incident-console checkout")
    if importlib.util.find_spec("pgserver") is None:
        parser.error("needs the `pgserver` wheel (a bundled disposable Postgres): uv run --with pgserver python ...")

    report = Harness(code_dir=args.code_dir.resolve(), repeat=args.repeat, quiet=args.quiet).run(args.rtt_ms)
    print(f"code: {report.code_dir}\npostgres: {report.postgres} (local, no TLS, no pooler; latency injected)\n")
    print(render(report, args.rtt_ms))
    if args.json:
        args.json.write_text(json.dumps(asdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
