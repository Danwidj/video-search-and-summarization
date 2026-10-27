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

"""Size and length of every held-out evaluation video, before any model call.

For each video in the split manifests (``eval_data/split_*.json``): resolve its
GT filename to exactly one R2 object (``eval_video_resolution``, exact basename,
and it must equal the manifest's recorded key), then read its size (R2
``HeadObject`` ``ContentLength``) and its length (the MP4 ``mvhd`` header via
ranged GETs, ``video_duration.r2_video_metadata``). Nothing is downloaded and no
model is called. A value that cannot be read is ``null`` and counted, never
guessed.

Writes ``eval_data/results/dataset_stats.json`` (per-video rows plus summary
statistics overall and per category) and ``dataset_stats.csv`` (per-video rows).
``eval_benchmark_export.py`` reads it. Usage::

    uv run python scripts/eval_dataset_stats.py
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_ingest_gt import EVAL_DATA_DIR  # noqa: E402
from eval_video_resolution import ResolutionError, resolve_filename  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"
BYTES_PER_MB = 1_000_000  # decimal megabytes
CSV_COLUMNS = ["category", "filename", "r2_object_key", "size_bytes", "size_mb", "duration_seconds", "error"]


def summary_stats(values: list[float | None]) -> dict:
    """n / mean / median / p90 / min / max / total over the known values; ``None``s are counted, not used.

    p90 interpolates linearly between the two nearest ranks (``statistics.quantiles``,
    inclusive method); with one value it is that value.
    """
    known = [float(v) for v in values if v is not None]
    stats: dict = {"n": len(known), "unknown": len(values) - len(known)}
    if not known:
        return {**stats, "mean": None, "median": None, "p90": None, "min": None, "max": None, "total": None}
    p90 = known[0] if len(known) == 1 else statistics.quantiles(known, n=10, method="inclusive")[-1]
    return {
        **stats,
        "mean": statistics.fmean(known),
        "median": statistics.median(known),
        "p90": p90,
        "min": min(known),
        "max": max(known),
        "total": math.fsum(known),
    }


def load_manifests(data_dir: Path = EVAL_DATA_DIR) -> list[dict]:
    paths = sorted(data_dir.glob("split_*.json"))
    if not paths:
        raise FileNotFoundError(
            f"no split manifests in {data_dir} - copy eval_reproducibility/split_*.json there "
            "(or run eval_generate_split.py)"
        )
    return [json.loads(path.read_text()) for path in paths]


def collect(
    manifests: list[dict], basename_index: dict[str, list[str]], metadata_fn: Callable[[str], dict]
) -> list[dict]:
    """One row per evaluation video, in manifest order. Unresolvable videos keep a row with ``error``."""
    rows = []
    for manifest in manifests:
        for filename in manifest["evaluation_videos"]:
            manifest_key = manifest["evaluation_videos_r2_keys"][filename]
            row = {"category": manifest["category"], "filename": filename, "r2_object_key": manifest_key,
                   "size_bytes": None, "size_mb": None, "duration_seconds": None, "error": ""}
            try:
                resolved = resolve_filename(filename, basename_index)
            except ResolutionError as exc:
                rows.append({**row, "error": str(exc)})
                continue
            if resolved != manifest_key:
                rows.append({**row, "error": f"R2 key {resolved!r} differs from manifest {manifest_key!r}"})
                continue
            metadata = metadata_fn(resolved)
            size = metadata.get("size_bytes")
            row.update(
                size_bytes=size,
                size_mb=size / BYTES_PER_MB if size is not None else None,
                duration_seconds=metadata.get("duration_seconds"),
            )
            if size is None:
                row["error"] = "size unreadable (HeadObject failed)"
            elif row["duration_seconds"] is None:
                row["error"] = "length unreadable from the MP4 header"
            rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    def block(subset: list[dict]) -> dict:
        return {
            "num_videos": len(subset),
            "num_unresolved": sum(1 for r in subset if r["size_bytes"] is None),
            "duration_seconds": summary_stats([r["duration_seconds"] for r in subset]),
            "size_bytes": summary_stats([r["size_bytes"] for r in subset]),
            "size_mb": summary_stats([r["size_mb"] for r in subset]),
        }

    categories = sorted({r["category"] for r in rows})
    return {"overall": block(rows), "by_category": {c: block([r for r in rows if r["category"] == c]) for c in categories}}


def write_outputs(rows: list[dict], results_dir: Path = RESULTS_DIR) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = results_dir / "dataset_stats.json", results_dir / "dataset_stats.csv"
    json_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "video_set": "held-out evaluation videos of the split manifests",
        "size_source": "R2 HeadObject ContentLength (MB = 10^6 bytes)",
        "duration_source": "MP4 moov/mvhd header, read with ranged R2 GETs (video_duration.py)",
        "summary": summarize(rows),
        "videos": rows,
    }, indent=2))
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main() -> int:
    import r2_videos
    from eval_video_resolution import build_basename_index
    from video_duration import r2_video_metadata

    if not r2_videos.configured():
        print("R2 is not configured (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET)")
        return 2
    rows = collect(load_manifests(), build_basename_index(r2_videos.list_video_keys()), r2_video_metadata)
    json_path, csv_path = write_outputs(rows)
    overall = summarize(rows)["overall"]
    duration, size = overall["duration_seconds"], overall["size_mb"]
    print(f"{overall['num_videos']} videos, {overall['num_unresolved']} unresolved, "
          f"{duration['unknown']} with unknown length")
    if duration["mean"] is not None:
        print(f"mean length {duration['mean']:.1f} s (median {duration['median']:.1f}, "
              f"min {duration['min']:.1f}, max {duration['max']:.1f})")
    if size["mean"] is not None:
        print(f"mean size {size['mean']:.2f} MB (median {size['median']:.2f}, "
              f"min {size['min']:.2f}, max {size['max']:.2f}, total {size['total']:.1f})")
    for row in rows:
        if row["error"]:
            print(f"  {row['category']} / {row['filename']}: {row['error']}")
    print(f"wrote {json_path} and {csv_path}")
    return 1 if any(r["error"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
