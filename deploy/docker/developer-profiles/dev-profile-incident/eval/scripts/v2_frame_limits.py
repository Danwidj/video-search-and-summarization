# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Each clip's last decodable frame, for RA1's frame-time clamp (C3-E, 2026-11-04). Offline: ffprobe only.

    uv run --frozen python scripts/v2_frame_limits.py OUT.json --ffprobe /path/to/ffprobe [--data-root DIR]

For every clip of ``dataset-manifest-v1`` it reads the video stream's packets (no decoding) and records the last
packet's presentation time, its duration (else one frame at the stream's average rate) and their sum, ``end_s``.
A planned frame time ``t`` is extractable when ``t < end_s``: on the 80 clips this matches the RA1 extraction exactly
(10,026 planned frames, the 8 missing ones all at or past ``end_s``). ``python -m evalv2 references ra1
--frame-limits OUT.json`` drops planned times past ``end_s`` and lists them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))


def probe(ffprobe: str, video: Path) -> dict[str, float]:
    """The last video packet's time, its duration and the end of its display (seconds)."""
    def run(*args: str) -> str:
        return subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", *args, str(video)],
                              capture_output=True, text=True, check=True).stdout

    packets = []
    for line in run("-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0").split():
        fields = line.strip(",").split(",")
        if fields and fields[0] not in ("", "N/A"):
            duration = float(fields[1]) if len(fields) > 1 and fields[1] not in ("", "N/A") else None
            packets.append((float(fields[0]), duration))
    if not packets:
        raise ValueError(f"{video}: no video packets")
    last, duration = max(packets, key=lambda p: p[0])
    if duration is None:
        duration = float(1 / Fraction(run("-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0").strip()))
    return {"last_pts_s": round(last, 6), "last_frame_duration_s": round(duration, 6), "end_s": round(last + duration, 6)}


def main() -> int:
    from evalv2.datasets.registry import EVAL_DIR, data_root

    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--ffprobe", required=True)
    ap.add_argument("--data-root", type=Path, default=None)
    a = ap.parse_args()
    manifest = json.loads((EVAL_DIR / "eval_reproducibility" / "dataset-manifest-v1.json").read_text(encoding="utf-8"))
    root = data_root(a.data_root)
    clips = {}
    for clip in manifest["clips"]:
        video = root / Path(clip["local_path"]).relative_to("eval_data")
        clips[clip["incident_id"]] = {**probe(a.ffprobe, video), "manifest_duration_s": float(clip["duration_seconds"]),
                                      "video_sha256": clip.get("sha256")}
    version = subprocess.run([a.ffprobe, "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    out = {"version": "frame-limits-v1", "rule": "a planned frame time t is kept when t < end_s",
           "ffprobe": version, "ffprobe_sha256": hashlib.sha256(Path(a.ffprobe).read_bytes()).hexdigest(),
           "clips": dict(sorted(clips.items()))}
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    short = {c: r["end_s"] for c, r in clips.items() if r["end_s"] < r["manifest_duration_s"]}
    print(json.dumps({"written": str(a.out), "clips": len(clips), "ending_before_manifest_duration": len(short)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
