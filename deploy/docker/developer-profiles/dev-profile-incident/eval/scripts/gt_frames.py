# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python-headless==4.10.0.84", "numpy>=1.26,<3"]
# ///
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

"""Timestamped evidence frames for the ground-truth video review (PR 4).

For each clip in a review-packet index, writes contact sheets with the video time burned
into every tile, so a reviewer (human or AI) can cite evidence by timestamp:

- ``window-<n>.jpg``: 1 frame per second over the annotated incident window +/- 10 s;
- ``overview.jpg``: 12 frames spread over the whole clip (omitted items, boundary errors).

``frames.json`` beside them records each sheet's tile timestamps and SHA-256, so the evidence
cited in a proposal can be checked against the exact images. Output is small JPEG (about
100-250 KB per sheet) under ``eval_data/gt_frames/`` (gitignored); the same clip and window
always give the same timestamps.

It runs in its own throwaway environment, so OpenCV is not an eval dependency (the same
pattern as the Supabase SQL harness)::

    uv run --no-project --python 3.12 --script scripts/gt_frames.py eval_data/gt_review_packets/index.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

TILE_WIDTH = 320
WINDOW_PAD_SECONDS = 10
WINDOW_FPS = 1.0
TILES_PER_SHEET = 24
SHEET_COLUMNS = 6
OVERVIEW_TILES = 12


def window_times(start: float | None, end: float | None, duration: float) -> list[float]:
    """1 fps over [start - 10, end + 10], clamped to the clip; the whole clip when the window is unknown."""
    lo = max(0.0, (start if start is not None else 0.0) - WINDOW_PAD_SECONDS)
    hi = min(duration, (end if end is not None else duration) + WINDOW_PAD_SECONDS)
    count = max(1, int(math.floor((hi - lo) * WINDOW_FPS)) + 1)
    return [round(min(lo + i / WINDOW_FPS, max(duration - 0.05, 0.0)), 2) for i in range(count)]


def overview_times(duration: float, tiles: int = OVERVIEW_TILES) -> list[float]:
    return [round((i + 0.5) * duration / tiles, 2) for i in range(tiles)]


def grab(capture, seconds: float):
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
    ok, frame = capture.read()
    if not ok:
        return None
    height, width = frame.shape[:2]
    tile = cv2.resize(frame, (TILE_WIDTH, max(1, round(height * TILE_WIDTH / width))), interpolation=cv2.INTER_AREA)
    label = f"{seconds:6.1f}s"
    cv2.rectangle(tile, (0, 0), (86, 22), (0, 0, 0), -1)
    cv2.putText(tile, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return tile


def sheet(tiles: list, columns: int = SHEET_COLUMNS):
    height = max(t.shape[0] for t in tiles)
    blank = np.zeros((height, TILE_WIDTH, 3), dtype=np.uint8)
    padded = [cv2.copyMakeBorder(t, 0, height - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    while len(padded) % columns:
        padded.append(blank)
    rows = [np.hstack(padded[i:i + columns]) for i in range(0, len(padded), columns)]
    return np.vstack(rows)


def write_sheet(path: Path, capture, times: list[float]) -> dict:
    tiles, used = [], []
    for seconds in times:
        tile = grab(capture, seconds)
        if tile is not None:
            tiles.append(tile)
            used.append(seconds)
    if not tiles:
        return {"file": path.name, "times": [], "sha256": None}
    cv2.imwrite(str(path), sheet(tiles), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return {"file": path.name, "times": used, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def frames_for(clip_path: Path, out_dir: Path, start: float | None, end: float | None) -> dict:
    capture = cv2.VideoCapture(str(clip_path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {clip_path}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    duration = frames / fps if fps else 0.0
    out_dir.mkdir(parents=True, exist_ok=True)
    times = window_times(start, end, duration)
    sheets = [write_sheet(out_dir / f"window-{n + 1}.jpg", capture, times[i:i + TILES_PER_SHEET])
              for n, i in enumerate(range(0, len(times), TILES_PER_SHEET))]
    sheets.append(write_sheet(out_dir / "overview.jpg", capture, overview_times(duration)))
    capture.release()
    record = {"clip": clip_path.name, "clip_sha256": None, "duration_seconds": round(duration, 3),
              "window": [start, end], "pad_seconds": WINDOW_PAD_SECONDS, "window_fps": WINDOW_FPS, "sheets": sheets}
    (out_dir / "frames.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Write timestamped contact sheets for the ground-truth video review.")
    parser.add_argument("index", type=Path, help="index.json written by gt_review_packet.py")
    parser.add_argument("--only", nargs="*", help="Incident ids to (re)build; default all in the index")
    args = parser.parse_args()
    index = json.loads(args.index.read_text())
    base = args.index.resolve().parents[2]  # eval/
    for entry in index["incidents"]:
        if args.only and entry["incident_id"] not in args.only:
            continue
        record = frames_for(base / entry["clip_local_path"], base / entry["frames_dir"], entry["start"], entry["end"])
        record["clip_sha256"] = entry["clip_sha256"]
        (base / entry["frames_dir"] / "frames.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"{entry['incident_id']}: {len(record['sheets'])} sheets, {record['duration_seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
