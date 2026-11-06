#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stores the whole frame of every evidence_crops row that has none (rows made before the agent stored frames).

For each row with an image and no frame: reads the frame the console cuts from the stored video at the row's box second
(GET <console>/api/reports/<video>/frame?t=), uploads it to R2 as <crop image key without .jpg>-frame.jpg (never
overwriting an object), and sets evidence_crops.frame. report_revisions is append-only and is not touched.

Dry run unless --apply. Reads INCIDENT_DB_DSN and R2_* from the environment (the profile's .env.local).

    set -a; . ./.env.local; set +a
    uv run --no-project --with 'psycopg[binary]' --with boto3 python scripts/backfill_evidence_frames.py \
        --console http://localhost:3250 [--apply]
"""

from __future__ import annotations

import argparse
import os
import urllib.parse
import urllib.request

import boto3
import psycopg
from botocore.exceptions import ClientError

ROWS = """
SELECT e.revision_id, e.item_type, e.item_id, e.image, e.timestamp_seconds, r.video_id
FROM public.evidence_crops AS e
JOIN public.report_revisions AS r ON r.id = e.revision_id
WHERE e.frame IS NULL AND e.image IS NOT NULL AND e.image <> ''
ORDER BY e.revision_id, e.item_type, e.item_id
"""


def frame_key(image: str) -> str:
    return (image[:-4] if image.lower().endswith(".jpg") else image) + "-frame.jpg"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--console", required=True, help="a running incident-console-v2, e.g. http://localhost:3250")
    parser.add_argument("--apply", action="store_true", help="upload and update; without it only list")
    args = parser.parse_args()

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"]
    stored = 0
    with psycopg.connect(os.environ["INCIDENT_DB_DSN"]) as conn:
        rows = conn.execute(ROWS).fetchall()
        for revision_id, item_type, item_id, image, seconds, video_id in rows:
            key = frame_key(image)
            print(f"{'store' if args.apply else 'would store'} {video_id} {item_type}:{item_id} t={seconds} -> {key}")
            if not args.apply:
                continue
            try:
                s3.head_object(Bucket=bucket, Key=key)
                raise SystemExit(f"{key} already exists; not overwriting")
            except ClientError as error:
                if error.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                    raise
            url = f"{args.console.rstrip('/')}/api/reports/{urllib.parse.quote(video_id)}/frame?t={float(seconds)}"
            with urllib.request.urlopen(url, timeout=60) as response:
                jpeg = response.read()
            s3.put_object(Bucket=bucket, Key=key, Body=jpeg, ContentType="image/jpeg")
            conn.execute(
                "UPDATE public.evidence_crops SET frame = %s WHERE revision_id = %s AND item_type = %s AND item_id = %s",
                (key, revision_id, item_type, item_id),
            )
            conn.commit()
            stored += 1
    print(f"{len(rows)} rows without a frame; {stored} stored")


if __name__ == "__main__":
    main()
