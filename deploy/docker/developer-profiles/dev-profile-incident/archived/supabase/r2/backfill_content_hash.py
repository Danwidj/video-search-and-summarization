# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fill videos.content_sha256 for every video that has none, from its R2 object. Deletes nothing.

    cd archived/supabase/r2 && uv run --no-project --with boto3 python backfill_content_hash.py \
        --env-file ../../../.env.local [--apply]

Dry run by default: it streams each video's object from R2, hashes it (SHA-256, lower-case hex) and prints
the plan. With --apply it sets the hash on each row that has none (PATCH filtered on content_sha256 being
null, so a hash set by the console meanwhile is never overwritten).

If two videos would share a hash (the same clip stored twice), it stops before writing anything, names
the rows and exits with status 2. Nothing is deleted or merged: a person decides.

The hash of a video the console converted to H.264 is of the stored (converted) bytes, not of the original
upload, so a re-upload of the original file is not caught for that video. A video whose object is missing
is reported and skipped. Safe to run again: rows that already have a hash are left alone.

Credentials come from --env-file (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET,
INCIDENT_SUPABASE_URL, INCIDENT_SUPABASE_SERVICE_ROLE_KEY) and are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

from migrate_r2_names import Rest, not_found, read_env

CHUNK = 8 * 1024 * 1024


def sha256_of_object(client: Any, bucket: str, key: str) -> str | None:
    """SHA-256 of an R2 object, streamed; None when the object does not exist."""
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as error:
        if not_found(error):
            return None
        raise
    digest = hashlib.sha256()
    for chunk in iter(lambda: body.read(CHUNK), b""):
        digest.update(chunk)
    return digest.hexdigest()


def find_collisions(hashes: dict[str, str]) -> dict[str, list[str]]:
    """hash -> video ids, for every hash held by more than one video."""
    by_hash: dict[str, list[str]] = defaultdict(list)
    for video_id, value in sorted(hashes.items()):
        by_hash[value].append(video_id)
    return {value: ids for value, ids in by_hash.items() if len(ids) > 1}


def set_hash(db: Rest, video_id: str, value: str) -> bool:
    """Set the hash where none is set; True when a row changed."""
    request = urllib.request.Request(
        db.base + f"videos?id=eq.{urllib.parse.quote(video_id)}&content_sha256=is.null",
        data=json.dumps({"content_sha256": value}).encode(),
        headers={**db.headers, "Prefer": "return=representation"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return bool(json.loads(response.read() or "[]"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"videos {video_id}: HTTP {error.code} {error.read().decode()[:300]}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--apply", action="store_true", help="write the hashes (default: dry run)")
    args = parser.parse_args(argv)
    env = read_env(args.env_file)
    missing = [
        k
        for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET", "INCIDENT_SUPABASE_URL", "INCIDENT_SUPABASE_SERVICE_ROLE_KEY")
        if not env.get(k)
    ]
    if missing:
        raise SystemExit(f"Missing in {args.env_file}: {', '.join(missing)}")

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=env["R2_ACCESS_KEY"],
        aws_secret_access_key=env["R2_SECRET_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    bucket = env["R2_BUCKET"]
    db = Rest(env["INCIDENT_SUPABASE_URL"], env["INCIDENT_SUPABASE_SERVICE_ROLE_KEY"])

    videos = db.table("videos", "id,filepath,content_sha256")
    hashes = {v["id"]: v["content_sha256"] for v in videos if v.get("content_sha256")}
    todo = [v for v in videos if not v.get("content_sha256") and v.get("filepath")]
    computed: dict[str, str] = {}
    skipped: list[str] = []
    for video in todo:
        value = sha256_of_object(client, bucket, video["filepath"])
        if value is None:
            skipped.append(f"{video['id']} ({video['filepath']}: object not found)")
            continue
        computed[video["id"]] = value
        print(f"hashed {video['id']}  {video['filepath']}  {value[:12]}")

    collisions = find_collisions({**hashes, **computed})
    for value, ids in collisions.items():
        print(f"SAME CONTENT {value[:12]}: {', '.join(ids)}")
    print(f"\nvideos {len(videos)}, already hashed {len(hashes)}, to hash {len(todo)}, hashed now {len(computed)}, skipped {len(skipped)}")
    for line in skipped:
        print(f"skipped {line}")
    if collisions:
        print("Stopped: two or more videos hold the same content. Nothing was written and nothing was deleted.")
        return 2
    if not args.apply:
        print("Dry run: nothing written. Re-run with --apply.")
        return 0
    written = sum(set_hash(db, video_id, value) for video_id, value in computed.items())
    print(f"Wrote {written} hashes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
