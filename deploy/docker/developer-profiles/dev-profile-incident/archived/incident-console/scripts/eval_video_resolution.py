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

"""GT filename -> R2 object -> local cached file, for the P1 multi-model eval.

Exact-basename resolution only. Never falls back to ``r2_videos.py``'s
category-alias matching (``category_matches``/``map_incidents_to_video_keys``)
- that path is documented there as demo-only and "never presented as the
actual incident evidence," and would silently substitute the wrong video for
a real ground-truth row.

Three resolution outcomes, no others:
- zero matches for a basename  -> ResolutionError (missing video)
- multiple matches for a basename -> ResolutionError (ambiguous)
- exactly one match -> proceeds to download/cache

Downloaded videos are cached under ``eval_data/video_cache/`` (gitignored)
so repeated runs (spike, then per-model batch runs) don't refetch the same
file.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import r2_videos  # noqa: E402

EVAL_DATA_DIR = Path(__file__).resolve().parents[1] / "eval_data"
VIDEO_CACHE_DIR = EVAL_DATA_DIR / "video_cache"


class ResolutionError(Exception):
    """A GT filename could not be resolved to exactly one R2 object."""


def build_basename_index(keys: list[str]) -> dict[str, list[str]]:
    """``{basename: [full_key, ...]}`` over every key in the bucket listing.

    A multi-map, not a dict that silently overwrites on a duplicate basename -
    duplicates must be detected, not hidden.
    """
    index: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        index[PurePosixPath(key).name].append(key)
    return dict(index)


def resolve_filename(filename: str, basename_index: dict[str, list[str]]) -> str:
    """Exact-basename resolution for one GT filename. Returns the R2 object key.

    Raises ``ResolutionError`` for zero or multiple matches - the only two
    non-success outcomes; there is no silent fallback.
    """
    matches = basename_index.get(filename, [])
    if len(matches) == 0:
        raise ResolutionError(f"no R2 object found for GT filename {filename!r}")
    if len(matches) > 1:
        raise ResolutionError(f"ambiguous: {len(matches)} R2 objects match GT filename {filename!r}: {matches}")
    return matches[0]


def download_and_cache(object_key: str, filename: str) -> Path:
    """Download ``object_key`` into the local video cache, skipping if already present.

    Returns the local path. Raises ``ResolutionError`` if the download fails
    (R2 not configured, or the object could not be fetched).
    """
    VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = VIDEO_CACHE_DIR / filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    video_bytes = r2_videos.download_video_bytes(object_key)
    if video_bytes is None:
        raise ResolutionError(f"failed to download R2 object {object_key!r} (R2 not configured, or object missing)")
    dest.write_bytes(video_bytes)
    return dest


def resolve_and_cache(filename: str, basename_index: dict[str, list[str]]) -> tuple[str, Path]:
    """Resolve one GT filename and ensure it is downloaded locally.

    Returns ``(r2_object_key, local_path)``. This is the one entry point the
    split-manifest generator and the batch evaluation runner should both use.
    """
    object_key = resolve_filename(filename, basename_index)
    local_path = download_and_cache(object_key, filename)
    return object_key, local_path


if __name__ == "__main__":
    # Manual smoke check: resolve+cache one filename per category.
    import json

    keys = r2_videos.list_video_keys()
    index = build_basename_index(keys)
    print(f"bucket listing: {len(keys)} video objects, {len(index)} distinct basenames")
    dupes = {b: ks for b, ks in index.items() if len(ks) > 1}
    print(f"basenames with >1 match bucket-wide: {len(dupes)}")

    sample = {
        "Assault": "Assault007_x264.mp4",
        "Burglary": "Burglary004_x264.mp4",
        "Explosion": None,
        "Road Accident": None,
        "Animal": "Animal001_x264.mp4",
    }
    for category, filename in sample.items():
        if filename is None:
            continue
        try:
            object_key, local_path = resolve_and_cache(filename, index)
            size = local_path.stat().st_size
            print(f"{category}: {filename} -> {object_key} -> {local_path} ({size} bytes)")
        except ResolutionError as exc:
            print(f"{category}: {filename} -> ERROR: {exc}")
