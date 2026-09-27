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

"""GT filename -> R2 object -> short-lived signed URL, for the P1 multi-model eval.

Exact-basename resolution only. Never falls back to ``r2_videos.py``'s
category-alias matching (``category_matches``/``map_incidents_to_video_keys``)
- that path is documented there as demo-only and "never presented as the
actual incident evidence," and would silently substitute the wrong video for
a real ground-truth row.

Three resolution outcomes, no others:
- zero matches for a basename  -> ResolutionError (missing video)
- multiple matches for a basename -> ResolutionError (ambiguous)
- exactly one match -> a presigned GET URL the model server fetches itself

The video is never downloaded locally: the contract sends every model the same
signed R2 URL the console uses (.docs/prompt-contract-plan.md, D9).
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import r2_videos  # noqa: E402

EVAL_DATA_DIR = Path(__file__).resolve().parents[1] / "eval_data"
# Signed per video immediately before its P1 call, so 1 h comfortably covers
# the call (240 s client timeout) even on a long batch run.
SIGNED_URL_TTL_SECONDS = 3600


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


def signed_url(object_key: str) -> str:
    """A presigned GET URL for ``object_key``. Raises ``ResolutionError`` if R2 is not configured."""
    if not r2_videos.configured():
        raise ResolutionError("R2 is not configured (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET)")
    return r2_videos.client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": object_key, "ResponseContentDisposition": "inline"},
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )


def resolve_and_sign(filename: str, basename_index: dict[str, list[str]]) -> tuple[str, str]:
    """Resolve one GT filename to its single R2 object and sign it.

    Returns ``(r2_object_key, signed_url)``. The batch evaluation runner's one
    entry point for turning a GT filename into model input.
    """
    object_key = resolve_filename(filename, basename_index)
    return object_key, signed_url(object_key)


if __name__ == "__main__":
    # Manual smoke check: resolve and sign one filename per category.
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
            object_key, _ = resolve_and_sign(filename, index)
            print(f"{category}: {filename} -> {object_key} (signed)")
        except ResolutionError as exc:
            print(f"{category}: {filename} -> ERROR: {exc}")
