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

"""Close-up video inspection for ground-truth adjudication: any time range, any frame rate, enlarged.

Writes one contact sheet of frames sampled at ``--fps`` over ``--start``..``--end`` seconds, each
tile scaled by ``--scale`` (the clips are about 320x240) with its video time burned in, plus a JSON
sidecar with the tile times and the sheet's SHA-256, so cited evidence can be checked. Read-only on
the video; output goes wherever ``--out`` says (use ``eval_data/``, gitignored). It runs in its own
throwaway environment, so OpenCV is not an eval dependency::

    uv run --no-project --python 3.12 --script scripts/gt_frame_detail.py \\
        --clip eval_data/videos/explosion/Explosion011_x264.mp4 --start 27 --end 30 --fps 10 --scale 2 \\
        --out eval_data/gt_adjudication/Explosion011/burst-27-30.jpg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

MAX_TILES = 48


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--clip", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.clip))
    if not capture.isOpened():
        print(f"cannot open {args.clip}", file=sys.stderr)
        return 1
    native_fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    duration = (capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0) / native_fps if native_fps else 0.0
    start, end = max(0.0, args.start), min(args.end, max(duration - 0.05, 0.0))
    count = min(MAX_TILES, max(1, int((end - start) * args.fps) + 1))
    times = [round(start + i / args.fps, 2) for i in range(count) if start + i / args.fps <= end + 1e-6]
    tiles, used = [], []
    for seconds in times:
        capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = capture.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        tile = cv2.resize(frame, (round(width * args.scale), round(height * args.scale)), interpolation=cv2.INTER_CUBIC)
        cv2.rectangle(tile, (0, 0), (120, 30), (0, 0, 0), -1)
        cv2.putText(tile, f"{seconds:7.2f}s", (5, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(tile)
        used.append(seconds)
    capture.release()
    if not tiles:
        print("no frames read", file=sys.stderr)
        return 1
    h = max(t.shape[0] for t in tiles)
    w = max(t.shape[1] for t in tiles)
    padded = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, w - t.shape[1], cv2.BORDER_CONSTANT) for t in tiles]
    while len(padded) % args.columns:
        padded.append(np.zeros((h, w, 3), dtype=np.uint8))
    sheet = np.vstack([np.hstack(padded[i:i + args.columns]) for i in range(0, len(padded), args.columns)])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    record = {"clip": args.clip.name, "start": start, "end": end, "fps": args.fps, "scale": args.scale,
              "times": used, "native_fps": round(native_fps, 3), "duration_seconds": round(duration, 3),
              "sha256": hashlib.sha256(args.out.read_bytes()).hexdigest()}
    args.out.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("clip", "start", "end", "fps", "sha256")} | {"tiles": len(used)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
