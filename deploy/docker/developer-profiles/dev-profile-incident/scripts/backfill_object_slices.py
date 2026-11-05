#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rewrites slice_start_seconds and slice_end_seconds of instrument and asset evidence_crops rows from their stored tracks.

The rule is evidenceSlice in incident-console-v2/src/modules/reports/domain/revision.ts: first to last detector-confirmed
track sample (score above 0; tracker-only samples are -0.1), widened to 2 s around its middle when shorter, then extended to include the box second; with no
confirmed sample or no track, 3 s either side of the box second (the row's timestamp_seconds). Clamped at 0. People (entity
rows) are not touched. R2 is only read. report_revisions is not touched.

Dry run unless --apply. With --apply the rows are first written to --export as JSON. Reads INCIDENT_DB_DSN and R2_* from the
environment (the profile's .env.local).

    set -a; . ./.env.local; set +a
    uv run --no-project --with 'psycopg[binary]' --with boto3 python scripts/backfill_object_slices.py \
        --export ~/some/dir/evidence_crops_slices_before.json [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from decimal import Decimal

import boto3
import psycopg

PADDING_SECONDS = 3.0
MIN_SLICE_SECONDS = 2.0
TRACK_KEY = re.compile(r"^evidence/.+-track\.json$")

ROWS = """
SELECT e.revision_id, e.item_type, e.item_id, e.timestamp_seconds, e.slice_start_seconds, e.slice_end_seconds,
       (SELECT x ->> 'track' FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(r.evidence) = 'array' THEN r.evidence ELSE '[]'::jsonb END) AS x
        WHERE x ->> 'item_type' = e.item_type AND x ->> 'item_id' = e.item_id LIMIT 1) AS track
FROM public.evidence_crops AS e
JOIN public.report_revisions AS r ON r.id = e.revision_id
WHERE e.item_type IN ('instrument', 'asset')
ORDER BY e.revision_id, e.item_type, e.item_id
"""


def confirmed_span(value: object) -> tuple[float, float] | None:
    samples = (
        value
        if isinstance(value, list)
        else value.get("samples")
        if isinstance(value, dict)
        else None
    )
    if not isinstance(samples, list):
        return None
    times = [
        float(s["t"])
        for s in samples
        if isinstance(s, dict)
        and isinstance(s.get("t"), (int, float))
        and s["t"] >= 0
        and isinstance(s.get("score"), (int, float))
        and s["score"] > 0
    ]
    return (min(times), max(times)) if times else None


def object_slice(
    box_second: float, span: tuple[float, float] | None
) -> tuple[float, float]:
    start, end = (
        (box_second - PADDING_SECONDS, box_second + PADDING_SECONDS)
        if span is None
        else span
    )
    if span is not None and end - start < MIN_SLICE_SECONDS:
        middle = (start + end) / 2
        start, end = middle - MIN_SLICE_SECONDS / 2, middle + MIN_SLICE_SECONDS / 2
    if span is not None:
        # the stored evidence moment is always inside the slice (137 A1: box at 0.07 s, confirmed from 2.4 s)
        start, end = min(start, box_second), max(end, box_second)
    start = max(0.0, start)
    return round(start, 3), round(max(start, end), 3)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--export",
        required=True,
        help="where --apply writes the rows before changing them",
    )
    parser.add_argument(
        "--apply", action="store_true", help="update the rows; without it only list"
    )
    args = parser.parse_args()

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"]
    with psycopg.connect(os.environ["INCIDENT_DB_DSN"]) as conn:
        rows = conn.execute(ROWS).fetchall()
        if args.apply:
            before = [
                {
                    "revision_id": r[0],
                    "item_type": r[1],
                    "item_id": r[2],
                    "timestamp_seconds": float(r[3]),
                    "slice_start_seconds": None if r[4] is None else float(r[4]),
                    "slice_end_seconds": None if r[5] is None else float(r[5]),
                }
                for r in rows
            ]
            with open(args.export, "w", encoding="utf-8") as handle:
                json.dump(before, handle, indent=1)
            print(f"exported {len(before)} rows to {args.export}")
        changed = 0
        for revision_id, item_type, item_id, second, old_start, old_end, track in rows:
            span = None
            if isinstance(track, str) and TRACK_KEY.match(track):
                span = confirmed_span(
                    json.loads(s3.get_object(Bucket=bucket, Key=track)["Body"].read())
                )
            start, end = object_slice(float(second), span)
            same = (
                old_start is not None
                and Decimal(str(start)) == old_start
                and Decimal(str(end)) == old_end
            )
            basis = (
                "confirmed"
                if span
                else ("no confirmed sample" if track else "no track")
            )
            old = (
                f"{float(old_start):g}-{float(old_end):g}"
                if old_start is not None
                else "none"
            )
            print(
                f"{'same ' if same else 'set  '} rev {revision_id} {item_type}:{item_id} {old} -> {start:g}-{end:g} ({basis})"
            )
            if same or not args.apply:
                continue
            conn.execute(
                "UPDATE public.evidence_crops SET slice_start_seconds = %s, slice_end_seconds = %s "
                "WHERE revision_id = %s AND item_type = %s AND item_id = %s",
                (start, end, revision_id, item_type, item_id),
            )
            changed += 1
        conn.commit()
    print(
        f"{len(rows)} instrument and asset rows; {changed} {'updated' if args.apply else 'to update (dry run)'}"
    )


if __name__ == "__main__":
    main()
