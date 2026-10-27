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

"""Write the per-video review packets an AI or human reviewer works from (PR 4).

One packet per video that has a finding only the video (or a person) can settle:
``rule_based_proposal`` and ``needs_video_review`` entries. A packet holds exactly the
inputs the correction prompt allows (``ground_truth/correction_prompts/gt-correction-v1.0.md``):

1. the original human annotation of that video (all four sheets, documented columns only);
2. the PR 3 findings for it (change id, rule, field, original value, guideline reference);
3. the clip (local verified copy and SHA-256) and the incident window;
4. where its timestamped contact sheets go (``gt_frames.py`` writes them).

It never reads model outputs, scores or experiment prompts (``guard_inputs``). Packets
contain annotation text, so they are written under ``eval_data/`` (gitignored).

Usage (from ``eval/``)::

    uv run python scripts/gt_review_packet.py
    uv run --no-project --python 3.12 --script scripts/gt_frames.py eval_data/gt_review_packets/index.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ground_truth_correction as gtc  # noqa: E402
import ground_truth_review as gtr  # noqa: E402
import openpyxl  # noqa: E402
from dataset_manifest import canonical_basename  # noqa: E402
from gt_review_build import DEFAULT_MANIFEST, DEFAULT_SOURCE, EVAL_DIR, sha256_file  # noqa: E402

DEFAULT_OUT = EVAL_DIR / "eval_data" / "gt_review_packets"
PROMPT_PATH = EVAL_DIR / "ground_truth" / "correction_prompts" / f"{gtc.CORRECTION_PROMPT_VERSION}.md"
VIDEO_CLASSES = ("rule_based_proposal", "needs_video_review")


def _plain(value):
    return value if isinstance(value, (int, float, str, bool)) or value is None else str(value)


def build_packets(values, manifest: dict, changes: list[gtr.Change]) -> dict[str, dict]:
    rows = gtr.read_data_rows(values)
    clips = {c["incident_id"]: c for c in manifest["clips"]}
    findings: dict[str, list[gtr.Change]] = defaultdict(list)
    for change in changes:
        if change.change_type in VIDEO_CLASSES:
            findings[change.incident_id].append(change)
    packets = {}
    for incident_id in sorted(findings):
        if not gtc.SAFE_ID.match(incident_id):
            raise ValueError(f"unexpected incident id {incident_id!r}")
        annotation = {}
        for sheet, spec in gtr.SHEETS.items():
            seen = set()
            annotation[sheet] = []
            for _, record in rows[sheet]:
                if gtr._clean(record.get(spec["incident"])) != incident_id:
                    continue
                clean = {c: _plain(record.get(c)) for c in spec["columns"] if c not in ("Labelled_By", "Labelled_DateTime")}
                clean["Filename"] = canonical_basename(str(clean.get("Filename") or "").strip())
                key = json.dumps(clean, sort_keys=True, default=str)
                if key not in seen:  # exact duplicates (R02) are shown once
                    seen.add(key)
                    annotation[sheet].append(clean)
        clip = clips[incident_id]
        start, end = gtc.incident_window(rows, incident_id)
        packets[incident_id] = {
            "incident_id": incident_id,
            "guidelines": gtr.GUIDELINE_VERSION,
            "correction_prompt": gtc.CORRECTION_PROMPT_VERSION,
            "clip": {"filename": clip["filename"], "local_path": clip["local_path"], "sha256": clip.get("sha256"),
                     "duration_seconds": clip.get("duration_seconds")},
            "window": {"start": start, "end": end},
            "frames_dir": f"eval_data/gt_frames/{incident_id}",
            "annotation": annotation,
            "findings": [{"change_id": c.change_id, "rule": c.rule, "class": c.change_type,
                          "what": gtr.RULES[c.rule][1], "guideline_ref": c.guideline_ref, "sheet": c.sheet,
                          "record_id": str(c.record_id), "field": c.field, "original_value": _plain(c.original_value),
                          "audit_proposed_value": _plain(c.proposed_value) if not isinstance(c.proposed_value, dict)
                          else c.proposed_value, "detail": c.reason}
                         for c in findings[incident_id]],
        }
    return packets


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the per-video ground-truth review packets.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    gtc.guard_inputs([args.source, args.manifest, args.out_dir])
    source_hash = sha256_file(args.source)
    manifest = json.loads(args.manifest.read_text())
    values = openpyxl.load_workbook(args.source, data_only=True)
    changes, _ = gtr.audit(values, manifest)
    packets = build_packets(values, manifest, changes)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for incident_id, packet in packets.items():
        (args.out_dir / f"{incident_id}.json").write_text(json.dumps(packet, indent=2, default=str) + "\n")
    index = {
        "source_sha256": source_hash,
        "findings_sha256": gtr.change_log_digest(changes),  # before appended rows get their row number
        "correction_prompt": gtc.CORRECTION_PROMPT_VERSION,
        "correction_prompt_sha256": sha256_file(PROMPT_PATH),
        "incidents": [{"incident_id": i, "clip_local_path": p["clip"]["local_path"], "clip_sha256": p["clip"]["sha256"],
                       "frames_dir": p["frames_dir"], "start": p["window"]["start"], "end": p["window"]["end"],
                       "findings": len(p["findings"])} for i, p in packets.items()],
    }
    (args.out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    if sha256_file(args.source) != source_hash:
        raise RuntimeError("the source workbook changed while writing packets")
    print(json.dumps({"packets": len(packets), "findings": sum(len(p["findings"]) for p in packets.values()),
                      "findings_sha256": index["findings_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
