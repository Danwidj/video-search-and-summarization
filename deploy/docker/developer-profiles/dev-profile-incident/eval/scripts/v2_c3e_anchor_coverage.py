# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E reference coverage at the evidence seconds: GT object x anchor second of its own kind (offline).

    python3 scripts/v2_c3e_anchor_coverage.py --c3e DIR --half dev|test

The development half must reproduce `tiers/dev/anchor-coverage-v1.json`, which checks this counting.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

KIND = {"E": "entity", "I": "instrument", "A": "asset"}
NOTES = Path("/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0-c3e-notes-v1.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--c3e", type=Path, required=True)
    ap.add_argument("--half", required=True)
    a = ap.parse_args()
    vis = json.loads((a.c3e / "tiers" / a.half / "visibility-tiers.json").read_text())
    box = json.loads((a.c3e / "tiers" / a.half / "box-tiers.json").read_text())
    sampling = json.loads((a.c3e / "boxes" / a.half / "sampling.json").read_text())["sampling"]
    flags = {f"{n['clip']}-{i}" for n in json.loads(NOTES.read_text())["notes"] if n["affects_identity"] for i in n["items"]}
    out: dict = collections.defaultdict(collections.Counter)
    for key, seconds in vis.items():
        clip, item = key.rsplit("-", 1)
        kind = KIND[item[0]]
        entry = sampling.get(clip, {}).get(kind)
        for s in (entry or {}).get("anchors", []):
            v = seconds.get(str(s)) or {"tier": "unresolved"}
            b = box.get(key, {}).get(str(s)) or {}
            if key in flags:
                out[kind]["gt_identity_flag"] += 1
            elif v["tier"] == "unresolved":
                out[kind]["visibility_unresolved"] += 1
            elif not v.get("visible"):
                out[kind]["not_visible_ref"] += 1
            elif b.get("tier") in ("consensus", "adjudicated"):
                out[kind][f"box_{b['tier']}"] += 1
            else:
                out[kind]["visible_box_unresolved"] += 1
    print(json.dumps({k: dict(v) for k, v in sorted(out.items())}, sort_keys=True))


if __name__ == "__main__":
    main()
