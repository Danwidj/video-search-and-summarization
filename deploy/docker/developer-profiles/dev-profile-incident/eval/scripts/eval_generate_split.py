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

"""Generate (once) and persist the per-category few-shot/held-out video split.

Seeded random selection, not "first N" (avoids upload-order bias) and not
unseeded random (not reproducible). Once written, ``eval_data/split_<category
>.json`` is the source of truth for later runs - they *read* the manifest
rather than re-sampling, so the split stays stable even if the video set
later grows. Every filename's resolved R2 object key is persisted alongside
it (never re-derived silently) so every result is traceable back to the
exact object analysed.

Usage::

    .venv/bin/python3 scripts/eval_generate_split.py [--seed 42] [--num-few-shot 5] [--force]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_gt_schema import load_gt_index  # noqa: E402
from eval_video_resolution import EVAL_DATA_DIR, ResolutionError, build_basename_index, resolve_filename  # noqa: E402
import r2_videos  # noqa: E402

DEFAULT_SEED = 42
DEFAULT_NUM_FEW_SHOT = 5


def split_path(category: str) -> Path:
    safe = category.lower().replace(" ", "_")
    return EVAL_DATA_DIR / f"split_{safe}.json"


def generate_split(category: str, filenames: list[str], *, seed: int, num_few_shot: int) -> dict:
    ordered = sorted(filenames)  # deterministic input order before sampling
    rng = random.Random(seed)
    few_shot = sorted(rng.sample(ordered, min(num_few_shot, len(ordered))))
    evaluation = sorted(f for f in ordered if f not in set(few_shot))
    return {
        "category": category,
        "seed": seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "few_shot_demo_videos": few_shot,
        "evaluation_videos": evaluation,
    }


def resolve_r2_keys(manifest: dict, basename_index: dict[str, list[str]]) -> dict:
    """Add each filename's resolved R2 object key, in place. Raises on any
    zero/multiple-match filename - never silently drops or guesses."""
    for field in ("few_shot_demo_videos", "evaluation_videos"):
        resolved = {}
        for filename in manifest[field]:
            resolved[filename] = resolve_filename(filename, basename_index)
        manifest[f"{field}_r2_keys"] = resolved
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--num-few-shot", type=int, default=DEFAULT_NUM_FEW_SHOT)
    parser.add_argument("--force", action="store_true", help="Regenerate even if a manifest already exists.")
    args = parser.parse_args()

    gt_index = load_gt_index()
    basename_index = build_basename_index(r2_videos.list_video_keys())
    EVAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

    for category, rows in gt_index["by_category"].items():
        path = split_path(category)
        if path.exists() and not args.force:
            print(f"{category}: manifest already exists at {path}, skipping (--force to regenerate)")
            continue

        filenames = [r["filename"] for r in rows]
        manifest = generate_split(category, filenames, seed=args.seed, num_few_shot=args.num_few_shot)
        try:
            resolve_r2_keys(manifest, basename_index)
        except ResolutionError as exc:
            print(f"{category}: ABORTED, resolution error: {exc}")
            continue

        path.write_text(json.dumps(manifest, indent=2))
        print(
            f"{category}: {len(manifest['few_shot_demo_videos'])} few-shot + "
            f"{len(manifest['evaluation_videos'])} evaluation -> {path}"
        )


if __name__ == "__main__":
    main()
