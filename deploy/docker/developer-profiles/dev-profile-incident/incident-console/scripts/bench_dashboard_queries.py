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

"""Cost of the Dashboard's evidence fetch: the old per-incident loop vs the batched, cached path.

Two modes:

    # Model (default): the app's own 36-incident seed in a throwaway SQLite file, with a fixed
    # delay injected before every statement to stand in for a remote Postgres round trip.
    uv run python scripts/bench_dashboard_queries.py --latency-ms 0 30 80

    # Measurement: an existing database, read-only, over its real network. Nothing is written,
    # no latency is injected and the DSN is never printed.
    uv run python scripts/bench_dashboard_queries.py --dsn "$INCIDENT_DB_DSN"

It prints a markdown table of SQL statements (what SQLAlchemy executed), connection checkouts and
median wall-clock time for: the per-incident loop the page used to run (3 statements and 3
connection checkouts per incident), the batched fetch on a cold cache (3 statements, 1 checkout)
and on a warm cache (nothing). SQLite timings are a model, not a measurement of Postgres: they
count one injected delay per statement, whereas psycopg2 against Postgres also pays a pre-ping, a
BEGIN and a ROLLBACK round trip on every checkout. ``--checkout-round-trips 3`` adds that.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# There is no Streamlit runtime in this script, and st.cache_data says so once per process; that is expected here.
logging.getLogger("streamlit.runtime.caching.cache_data_api").addFilter(
    lambda r: "No runtime found" not in r.getMessage()
)

from sqlalchemy import event  # noqa: E402

from dashboard_data import clear_evidence_cache, evidence_rows  # noqa: E402
from db import IncidentDB  # noqa: E402
from db_reports import DBReports  # noqa: E402
from scripts.seed_supabase import seed  # noqa: E402


def per_incident_loop(handle: IncidentDB, reports: list[dict]) -> None:
    """What ``pages/3_Dashboard.py`` ran before batching: three statements, three checkouts per incident."""
    for report in reports:
        incident_id, model_run_id = report["id"], report.get("model_run_id")
        handle.list_incident_entities(incident_id, model_run_id)
        handle.list_incident_instruments(incident_id, model_run_id)
        handle.list_incident_assets(incident_id, model_run_id)


def measure(counters: dict, fn, repeats: int) -> tuple[float, int, int]:
    """Median wall-clock seconds, plus statements and connection checkouts of one call."""
    times = []
    for _ in range(repeats):
        counters.update(statements=0, checkouts=0)
        started = time.perf_counter()
        fn()
        times.append(time.perf_counter() - started)
    return statistics.median(times), counters["statements"], counters["checkouts"]


def instrument(handle: IncidentDB, delay: dict) -> dict:
    """Count statements / checkouts on ``handle``; sleep ``delay["statement"]`` / ``delay["checkout"]`` seconds on each."""
    counters = {"statements": 0, "checkouts": 0}

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        counters["statements"] += 1
        time.sleep(delay["statement"])

    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        counters["checkouts"] += 1
        time.sleep(delay["checkout"])

    event.listen(handle.engine, "before_cursor_execute", on_execute)
    event.listen(handle.engine, "checkout", on_checkout)
    return counters


def run(handle: IncidentDB, latencies_ms: list[float], checkout_round_trips: int, repeats: int, injected: bool):
    delay = {"statement": 0.0, "checkout": 0.0}
    counters = instrument(handle, delay)
    reports = DBReports(handle).list_reports()
    rows = []
    for latency_ms in latencies_ms:
        delay["statement"] = latency_ms / 1000
        delay["checkout"] = latency_ms / 1000 * checkout_round_trips
        # With any real or injected latency the loop takes seconds to minutes; once is enough.
        loop_repeats = repeats if injected and latency_ms < 10 else 1
        rows.append(
            (
                "per-incident loop (before)",
                latency_ms,
                *measure(counters, lambda: per_incident_loop(handle, reports), loop_repeats),
            )
        )

        def cold():
            clear_evidence_cache()
            evidence_rows(handle, reports)

        rows.append(("batched, cache miss (after)", latency_ms, *measure(counters, cold, repeats)))
        evidence_rows(handle, reports)  # warm
        rows.append(
            (
                "batched, cache hit (after)",
                latency_ms,
                *measure(counters, lambda: evidence_rows(handle, reports), repeats),
            )
        )
    return len(reports), rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--latency-ms", type=float, nargs="+", default=[0, 30, 80], help="injected ms per statement (model mode)"
    )
    parser.add_argument(
        "--checkout-round-trips",
        type=int,
        default=0,
        help="extra round trips charged per connection checkout (model mode); 3 = pre-ping + BEGIN + ROLLBACK",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--dsn", help="measure this existing database, read-only, with its real latency")
    args = parser.parse_args(argv)

    if args.dsn:
        handle = IncidentDB.from_dsn(args.dsn)
        handle.healthcheck()  # open the pooled connection first, as a running app has
        count, rows = run(handle, [0], 0, args.repeats, injected=False)
        title = f"{count} incidents, measured over the database's real network (read-only)"
    else:
        with tempfile.TemporaryDirectory() as tmp:
            handle = IncidentDB.from_dsn(f"sqlite:///{tmp}/bench.db")
            handle.init_schema()
            seed(handle)
            count, rows = run(handle, args.latency_ms, args.checkout_round_trips, args.repeats, injected=True)
            handle.engine.dispose()
        extra = f" + {args.checkout_round_trips} round trips per checkout" if args.checkout_round_trips else ""
        title = f"{count} incidents, SQLite with an injected delay per statement{extra} (a model, not Postgres)"

    print(f"\n{title}\n")
    print("| path | latency | SQL statements | connection checkouts | wall-clock |")
    print("|---|---:|---:|---:|---:|")
    for path, latency_ms, seconds, statements, checkouts in rows:
        latency = "real" if args.dsn else f"{latency_ms:g} ms"
        print(f"| {path} | {latency} | {statements} | {checkouts} | {seconds * 1000:,.0f} ms |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
