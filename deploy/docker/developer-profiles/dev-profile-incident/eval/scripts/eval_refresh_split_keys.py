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

"""Re-resolve the R2 keys stored in the split manifests, keeping their membership.

The split manifests (``split_<category>.json``) name each video by its ground-truth
filename and store the R2 key it resolved to when the split was generated. When R2
objects move (2026-10-27: 24 clips moved into ``anomaly/demo/`` and renamed
``*_demo.mp4``), the stored keys go stale and ``eval_run.py`` skips those videos. This
rewrites only the two key maps, through the same resolver ``eval_run.py`` uses
(``_demo`` alias included), and refuses to write if any filename fails to resolve. The
seed, the filenames in each list and their order never change.

Usage (from ``eval/``)::

    uv run python scripts/eval_refresh_split_keys.py            # tracked manifests in eval_reproducibility/
    uv run python scripts/eval_refresh_split_keys.py --check    # report stale keys, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_video_resolution import (  # noqa: E402
    ResolutionError,
    build_basename_index,
    resolve_filename,
)

REPRODUCIBILITY_DIR = Path(__file__).resolve().parents[1] / "eval_reproducibility"
_LISTS = ("few_shot_demo_videos", "evaluation_videos")


def refresh_keys(manifest: dict, basename_index: dict[str, list[str]], *, refreshed_at: str) -> tuple[dict, list[dict]]:
    """A copy of ``manifest`` with current R2 keys, and the list of keys that changed.

    Raises ``ResolutionError`` if any filename resolves to zero or several objects.
    """
    refreshed = json.loads(json.dumps(manifest))
    changes = []
    for field in _LISTS:
        keys = {}
        for filename in manifest[field]:
            keys[filename] = resolve_filename(filename, basename_index)
            old = manifest.get(f"{field}_r2_keys", {}).get(filename)
            if old != keys[filename]:
                changes.append({"filename": filename, "old": old, "new": keys[filename]})
        refreshed[f"{field}_r2_keys"] = keys
    if changes:
        refreshed["r2_keys_refreshed_at"] = refreshed_at
    for field in _LISTS:
        assert refreshed[field] == manifest[field], "split membership must never change"
    return refreshed, changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-resolve split-manifest R2 keys; membership is unchanged.")
    parser.add_argument("--check", action="store_true", help="Report stale keys only; write nothing.")
    args = parser.parse_args()

    import r2_videos

    basename_index = build_basename_index(r2_videos.list_video_keys())
    refreshed_at = datetime.now(UTC).isoformat(timespec="seconds")
    stale = 0
    for path in sorted(REPRODUCIBILITY_DIR.glob("split_*.json")):
        manifest = json.loads(path.read_text())
        try:
            refreshed, changes = refresh_keys(manifest, basename_index, refreshed_at=refreshed_at)
        except ResolutionError as exc:
            print(f"{path.name}: ABORTED, {exc}")
            return 1
        stale += len(changes)
        for change in changes:
            print(f"  {path.name}: {change['filename']}: {change['old']} -> {change['new']}")
        if changes and not args.check:
            path.write_text(json.dumps(refreshed, indent=2))
        print(f"{path.name}: {len(changes)} key(s) {'stale' if args.check else 'updated'}")
    if not args.check and stale:
        print("Copy the refreshed manifests to eval_data/ for eval_run.py: cp eval_reproducibility/split_*.json eval_data/")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
