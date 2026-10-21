# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compare what readers see on midterm and on finals after the copy (read-only on both).

    cd supabase/tests && uv run --no-project --with 'psycopg[binary]' python parity_check.py --source-env <midterm env> --target-env <finals env>

Calls the dashboard, report-library and search RPCs with the same arguments on both databases and
prints every difference. Expected differences (and nothing else):
  * dashboard videos.uploaded / videos.withoutReport drop by the 8 broken uploads left behind;
  * library editedBy/editedAt are null where the copy cleared a status-change stamp;
  * search: entity crops labelled person now say human; the verified legacy run's window is in
    seconds ("0"/"18" instead of "0:00"/"0:18").
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import psycopg


def read_dsn(env_file: str) -> str:
    for line in Path(env_file).read_text().splitlines():
        match = re.match(r"^\s*INCIDENT_DB_DSN=(.*)$", line.strip())
        if match:
            return match.group(1).strip().strip('"').strip("'").replace("postgresql+psycopg2://", "postgresql://")
    raise SystemExit(f"INCIDENT_DB_DSN is not set in {env_file}")


DASHBOARD_CASES = [
    {},
    {"p_timezone": "Asia/Singapore"},
    {"p_type": "assault"},
    {"p_type": "animal attack", "p_timezone": "Asia/Singapore"},
    {"p_severity": "high"},
    {"p_severity": "low"},
    {"p_day_of_week": 2, "p_timezone": "Asia/Singapore"},
    {"p_period_start": "2026-09-27 00:00:00", "p_period_end": "2026-10-04 00:00:00"},
]
LIBRARY_CASES = [
    {"p_page_size": 1000},
    {"p_page_size": 1000, "p_scope": "official"},
    {"p_page_size": 1000, "p_type": "animal attack"},
    {"p_page_size": 1000, "p_status": "verified"},
    {"p_page_size": 1000, "p_search": "monkey"},
    {"p_page_size": 1000, "p_entity_types": ["human"]},
    {"p_page_size": 1000, "p_entities": ["child"]},
    {"p_page_size": 1000, "p_assets": ["door"], "p_evidence_match": "exact"},
    {"p_page_size": 1000, "p_sort": "severity-high", "p_timezone": "Asia/Singapore", "p_day_of_week": 6},
]


def call(cur: psycopg.Cursor, fn: str, args: dict) -> object:
    names = ", ".join(f"{k} => %({k})s" for k in args)
    cur.execute(f"SELECT public.{fn}({names})::TEXT", args)
    return json.loads(cur.fetchone()[0])


def diff(a: object, b: object, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            out += diff(a.get(key, "<missing>"), b.get(key, "<missing>"), f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {json.dumps(a)[:90]} -> {json.dumps(b)[:90]}"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", required=True)
    parser.add_argument("--target-env", required=True)
    args = parser.parse_args()
    with psycopg.connect(read_dsn(args.source_env)) as src, psycopg.connect(read_dsn(args.target_env)) as dst:
        src.read_only = dst.read_only = True
        s, d = src.cursor(), dst.cursor()
        for case in DASHBOARD_CASES:
            found = diff(call(s, "get_incident_dashboard", case), call(d, "get_incident_dashboard", case))
            print(f"dashboard {case}: {len(found)} difference(s)")
            for line in found:
                print("   ", line)
        for case in LIBRARY_CASES:
            a, b = call(s, "list_incident_report_summaries", case), call(d, "list_incident_report_summaries", case)
            found = diff(a, b)
            print(f"library {case}: {a['totalItems']} vs {b['totalItems']} reports, {len(found)} difference(s)")
            for line in found:
                print("   ", line)
        # Search: use a stored crop embedding as the query, so no embedding model is needed.
        s.execute("SELECT embedding::TEXT FROM public.evidence_crops ORDER BY incident_id, model_run_id, item_type, item_id LIMIT 1")
        query = s.fetchone()[0]
        rows = []
        for cur, schema in ((s, ""), (d, "extensions.")):
            cur.execute(
                f"SELECT * FROM public.search_evidence_items(%s::{schema}vector, 100, -1.0) ORDER BY incident_id, model_run_id, item_type, item_id",
                (query,),
            )
            cols = [c.name for c in cur.description]
            rows.append([dict(zip(cols, r)) for r in cur.fetchall()])
        print(f"search: {len(rows[0])} vs {len(rows[1])} hits")
        for a, b in zip(*rows):
            for key in a:
                if a[key] != b[key] and not (key == "similarity_score" and abs(a[key] - b[key]) < 1e-9):
                    print(f"    {a['model_run_id']} {a['item_type']} {a['item_id']} {key}: {a[key]!r} -> {b[key]!r}")
        src.rollback()
        dst.rollback()


if __name__ == "__main__":
    main()
