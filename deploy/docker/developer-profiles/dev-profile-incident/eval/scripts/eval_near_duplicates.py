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

"""Read-only perceptual-hash near-duplicate check across the split-v2 clips (plan §E).

Reads the local copies listed in ``eval_reproducibility/dataset-manifest-v1.json`` (each verified against its
recorded SHA-256 first), samples one frame per second (at most ``--max-frames``), and hashes each frame with a
64-bit DCT perceptual hash. Near-uniform frames (black, letterbox, fades) are skipped, since they match across
any two clips. For every pair of clips, ``overlap`` is the share of the shorter side's frames that have a frame in
the other clip within ``--max-distance`` bits. A pair at or above ``--flag`` is a **candidate** for a visual check,
not a confirmed duplicate: clips from the same camera or scene also share frames.

Writes nothing but ``--out`` (a new file) and never opens the dataset, split or results for writing. Needs
OpenCV and NumPy, which the eval venv does not have: run it with the agent venv's interpreter, isolated::

    ~/.cache/vss-agent-venv/bin/python -I scripts/eval_near_duplicates.py --out eval_data/audit/near-duplicates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
MANIFEST = EVAL_DIR / "eval_reproducibility" / "dataset-manifest-v1.json"
SPLIT = EVAL_DIR / "eval_reproducibility" / "split-v2.json"
MIN_FRAME_STD = 8.0  # grey-level standard deviation below which a frame is treated as uninformative


def phash(frame, cv2, np) -> int:
    """64-bit DCT perceptual hash: 32x32 grey, top-left 8x8 DCT block without DC, thresholded at its median."""
    grey = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA)
    block = cv2.dct(np.float32(grey))[:8, :8].flatten()[1:]
    bits = block > np.median(block)
    return int("".join("1" if b else "0" for b in bits), 2)


def clip_hashes(path: Path, max_frames: int, cv2, np) -> dict:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, round(fps)) if fps > 0 else 25
    indices = list(range(0, count, step))
    if len(indices) > max_frames:
        indices = [indices[round(i * (len(indices) - 1) / (max_frames - 1))] for i in range(max_frames)]
    hashes, skipped = [], 0
    for index in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok or frame is None:
            skipped += 1
            continue
        if float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).std()) < MIN_FRAME_STD:
            skipped += 1
            continue
        hashes.append(phash(frame, cv2, np))
    cap.release()
    return {"hashes": hashes, "sampled": len(indices), "uninformative_or_unreadable": skipped}


def overlap(a: list[int], b: list[int], max_distance: int) -> tuple[float, int]:
    """Share of the shorter list's hashes with a match in the other, and the number of matching frames."""
    short, other = (a, b) if len(a) <= len(b) else (b, a)
    if not short or not other:
        return 0.0, 0
    hits = sum(1 for h in short if min(bin(h ^ o).count("1") for o in other) <= max_distance)
    return hits / len(short), hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--max-distance", type=int, default=10, help="Hamming bits (of 64) for a frame match")
    parser.add_argument("--flag", type=float, default=0.3, help="overlap share that makes a pair a candidate")
    args = parser.parse_args()
    if args.out.exists():
        print(f"REFUSED: {args.out} exists", file=sys.stderr)
        return 2
    import cv2
    import numpy as np

    manifest = json.loads(MANIFEST.read_text())
    split = json.loads(SPLIT.read_text())
    half = {i: "dev" for i in split["dev"]} | {i: "test" for i in split["test"]}
    clips, problems = {}, []
    for clip in manifest["clips"]:
        if clip["incident_id"] not in half:
            continue
        path = EVAL_DIR / clip["local_path"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != clip["sha256"]:
            problems.append(f"{clip['incident_id']}: local copy missing or not the manifest's bytes")
            continue
        clips[clip["incident_id"]] = clip_hashes(path, args.max_frames, cv2, np)
    exact = {}
    for clip in manifest["clips"]:
        exact.setdefault(clip["sha256"], []).append(clip["incident_id"])
    ids = sorted(clips)
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            share, hits = overlap(clips[a]["hashes"], clips[b]["hashes"], args.max_distance)
            if hits:
                pairs.append({"a": a, "b": b, "halves": f"{half[a]}-{half[b]}", "overlap": round(share, 3),
                              "matching_frames": hits,
                              "frames": [len(clips[a]["hashes"]), len(clips[b]["hashes"])]})
    pairs.sort(key=lambda p: (-p["overlap"], -p["matching_frames"], p["a"], p["b"]))
    candidates = [p for p in pairs if p["overlap"] >= args.flag]
    out = {
        "method": {"hash": "64-bit DCT pHash (32x32 grey, 8x8 low-frequency block, median threshold)",
                   "sampling": f"1 frame per second, at most {args.max_frames} per clip",
                   "uninformative_frame_std_below": MIN_FRAME_STD, "frame_match_max_hamming": args.max_distance,
                   "pair_flag_overlap": args.flag, "split": split["version"], "manifest": MANIFEST.name},
        "clips": {"dev": sum(1 for i in ids if half[i] == "dev"), "test": sum(1 for i in ids if half[i] == "test"),
                  "frames_hashed": sum(len(c["hashes"]) for c in clips.values()),
                  "frames_skipped": sum(c["uninformative_or_unreadable"] for c in clips.values())},
        "problems": problems,
        "exact_duplicates": [v for v in exact.values() if len(v) > 1],
        "candidates": candidates,
        "cross_split_candidates": [p for p in candidates if p["halves"] in ("dev-test", "test-dev")],
        "top_pairs": pairs[:20],
        "pairs_with_any_matching_frame": len(pairs),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in ("clips", "problems", "exact_duplicates", "candidates",
                                          "pairs_with_any_matching_frame")}, indent=2))
    print(json.dumps(out["top_pairs"][:10], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
