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

"""Download and verify the evaluation videos from R2, and write the dataset manifest.

The dataset is every ``anomaly/<folder>/<file>.mp4`` object except ``anomaly/shooting/``
(``dataset_manifest.select_dataset_objects``). Each clip is downloaded to the gitignored
``eval_data/videos/<folder>/<original filename>``: through a ``.part`` file, retried with
backoff, verified (size, MD5 against a single-part ETag, SHA-256, MP4 duration) and only
then renamed. A rerun skips a clip whose local copy already verifies, so an interrupted
fetch resumes. R2 is only listed and read: nothing is uploaded, renamed or deleted.

The manifest ``eval_reproducibility/dataset-manifest-v1.json`` is tracked (no video, no
credentials) and records every clip's R2 key, ground-truth filename, sizes, digests and
duration, the skipped objects, and the integrity findings, including coverage of the
split manifests. The command exits non-zero when any finding is open.

Usage (from ``eval/``)::

    uv run python scripts/eval_fetch_videos.py --list          # inventory only: counts and size, no download
    uv run python scripts/eval_fetch_videos.py                 # download (resumable), verify, write the manifest
    uv run python scripts/eval_fetch_videos.py --verify-only   # re-hash local copies against the manifest, offline
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dataset_manifest as dm  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1]
VIDEOS_DIR = EVAL_DIR / "eval_data" / "videos"
REPRODUCIBILITY_DIR = EVAL_DIR / "eval_reproducibility"
MANIFEST_PATH = REPRODUCIBILITY_DIR / f"{dm.MANIFEST_VERSION}.json"
MAX_ATTEMPTS = 4


def list_dataset_prefix(client, bucket: str) -> list[dict]:
    """Every object under ``anomaly/`` with ``Key``/``Size``/``ETag``/``LastModified``."""
    objects = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=dm.DATASET_PREFIX):
        objects.extend(page.get("Contents", []))
    return objects


def split_membership(reproducibility_dir: Path = REPRODUCIBILITY_DIR) -> dict[str, str]:
    """``{filename: "few_shot" | "evaluation"}`` over the tracked split manifests."""
    membership: dict[str, str] = {}
    for path in sorted(reproducibility_dir.glob("split_*.json")):
        manifest = json.loads(path.read_text())
        for filename in manifest["few_shot_demo_videos"]:
            membership[filename] = "few_shot"
        for filename in manifest["evaluation_videos"]:
            membership[filename] = "evaluation"
    return membership


def download(client, bucket: str, obj: dict, dest: Path, *, sleep: Callable[[float], None] = time.sleep,
             max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Download one clip through ``dest.part``, verify it and rename it into place. Returns the verification."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    verified: dict = {"problems": ["not downloaded"]}
    for attempt in range(1, max_attempts + 1):
        try:
            body = client.get_object(Bucket=bucket, Key=obj["Key"])["Body"]
            with part.open("wb") as handle:
                for chunk in iter(lambda b=body: b.read(1024 * 1024), b""):
                    handle.write(chunk)
            verified = dm.verify_local_copy(part, obj)
        except Exception as exc:  # noqa: BLE001 - any transfer error is retried, then reported
            verified = {"problems": [f"download failed: {type(exc).__name__}: {exc}"]}
        if not verified["problems"]:
            part.replace(dest)
            verified["attempts"] = attempt
            return verified
        if attempt < max_attempts:
            sleep(2 ** (attempt - 1))
    part.unlink(missing_ok=True)
    verified["attempts"] = max_attempts
    return verified


def fetch(client, bucket: str, *, videos_dir: Path = VIDEOS_DIR, reproducibility_dir: Path = REPRODUCIBILITY_DIR,
          sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print) -> dict:
    """Download every dataset clip that is not already verified locally, and return the manifest."""
    selected, skipped = dm.select_dataset_objects(list_dataset_prefix(client, bucket))
    entries = []
    for obj in selected:
        dest = dm.local_path_for(videos_dir, obj["Key"])
        verified = dm.verify_local_copy(dest, obj) if dest.exists() else None
        if verified is not None and not verified["problems"]:
            action = "verified (already local)"
        else:
            verified = download(client, bucket, obj, dest, sleep=sleep)
            action = "downloaded" if not verified["problems"] else f"FAILED: {'; '.join(verified['problems'])}"
        log(f"  {obj['Key']}: {action}")
        entries.append(dm.manifest_entry(obj, verified, videos_dir=videos_dir, relative_to=videos_dir.parents[1]))
    findings = dm.integrity_findings(entries, split_membership(reproducibility_dir))
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    return dm.build_manifest(entries, skipped, findings, bucket=bucket, generated_at=generated_at)


def verify_only(manifest: dict, *, eval_dir: Path = EVAL_DIR) -> list[str]:
    """Re-hash every local copy named by ``manifest``; returns the problems (empty when all match)."""
    problems = []
    for clip in manifest["clips"]:
        path = eval_dir / clip["local_path"]
        if not path.exists():
            problems.append(f"{clip['local_path']}: missing")
            continue
        _, sha256 = dm.file_digests(path)
        if sha256 != clip["sha256"]:
            problems.append(f"{clip['local_path']}: SHA-256 differs from the manifest")
    return problems


def _r2():
    import r2_videos

    if not r2_videos.configured():
        raise SystemExit("R2 is not configured (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET)")
    return r2_videos.client(), os.environ["R2_BUCKET"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="Inventory only: no download, no manifest.")
    mode.add_argument("--verify-only", action="store_true", help="Re-hash local copies against the manifest; no R2.")
    args = parser.parse_args()

    if args.verify_only:
        problems = verify_only(json.loads(MANIFEST_PATH.read_text()))
        for problem in problems:
            print(f"  {problem}")
        print("verify-only:", "OK" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    client, bucket = _r2()
    if args.list:
        selected, skipped = dm.select_dataset_objects(list_dataset_prefix(client, bucket))
        print(f"dataset clips: {len(selected)}, {sum(int(o['Size']) for o in selected) / 1e9:.3f} GB")
        for item in skipped:
            print(f"  skipped {item['key']}: {item['reason']}")
        return 0

    print(f"fetching into {VIDEOS_DIR}")
    manifest = fetch(client, bucket)
    REPRODUCIBILITY_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    summary = manifest["summary"]
    print(f"{summary['clips']} clips, {summary['total_bytes'] / 1e9:.3f} GB -> manifest {MANIFEST_PATH}")
    if not manifest["integrity"]["ok"]:
        print("INTEGRITY FINDINGS:")
        for name, value in manifest["integrity"].items():
            if name != "ok" and value:
                print(f"  {name}: {value}")
        return 1
    print("integrity: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
