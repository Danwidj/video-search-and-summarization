# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E v0.2 freeze manifest (build or verify), written before the evaluation half's anchors are drawn.

    uv run --frozen python scripts/v2_c3e_freeze.py build|verify --c3e DIR

Pins by SHA-256: the v0.2 pre-registration, the sampler, tier, review and scoring code, the generation prompts and
their registry, the frame limits, the GT notes, the development sampling and tier records and the evaluation half's
visibility tiers, plus the rules' constants. ``verify`` re-hashes everything and fails on any difference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))
MANIFEST = EVAL / "methodology" / "c3e-freeze-manifest.json"
CODE = ("evalv2/references/c3e.py", "evalv2/references/c3e_v2.py", "evalv2/references/c3e_score.py",
        "evalv2/references/c3e_review.py", "evalv2/references/boxes.py", "evalv2/tasks/crops/scoring.py",
        "evalv2/tasks/pipeline/crops.py", "scripts/v2_c3e.py", "scripts/v2_c3e_dev_report.py",
        "evalv2/datasets/generation_prompts/registry.json", "methodology/c3e-preregistration-v0.2.md")
PROMPTS = ("gen-box-select-v1", "gen-box-validate-v1", "gen-visibility-v1", "gen-visibility-validate-v1",
           "gen-box-adjudicate-v1", "gen-visibility-adjudicate-v1", "gen-gt-discrepancy-check-v1")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(c3e: Path) -> dict:
    from evalv2.datasets import generation_prompts
    from evalv2.references import c3e as sampler
    from evalv2.references import c3e_v2

    data = {
        "frame_limits": c3e.parent / "box-references-v1" / "frame-limits-v1.json",
        "gt_notes_v1": Path("/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0-c3e-notes-v1.json"),
        "dev_sampling": c3e / "boxes" / "dev" / "sampling.json",
        "dev_box_tiers": c3e / "tiers" / "dev" / "box-tiers.json",
        "dev_visibility_tiers": c3e / "tiers" / "dev" / "visibility-tiers.json",
        "test_visibility_tiers_first_pass": c3e / "tiers" / "test" / "visibility-tiers-first-pass.json",
    }
    return {
        "manifest_version": "c3e-freeze-manifest-v1",
        "study": "C3-E v0.2, AI-referenced evidence-crop evaluation (not human-verified)",
        "code_sha256": {f: sha(EVAL / f) for f in CODE},
        "prompts_sha256": {p: hashlib.sha256(generation_prompts.prompt_text(p).encode()).hexdigest() for p in PROMPTS},
        "data_sha256": {k: sha(v) for k, v in data.items()},
        "rules": {"sampler_version": sampler.SAMPLER_VERSION, "decoy_seed": sampler.DECOY_SEED,
                  "decoy_ratio": sampler.DECOY_RATIO, "decoy_near_s": sampler.DECOY_NEAR_S,
                  "visibility_step_s": sampler.VISIBILITY_STEP_S, "agree_iou": c3e_v2.AGREE_IOU,
                  "map_iou": c3e_v2.MAP_IOU, "same_candidate_iou": c3e_v2.SAME_CANDIDATE_IOU,
                  "adjudication_confidence": c3e_v2.ADJ_CONFIDENCE,
                  "visibility_adjudication_max_seconds": c3e_v2.VIS_ADJ_MAX_SECONDS,
                  "correct_evidence_iou": 0.5, "sensitivity_iou": [0.3, 0.5, 0.7], "min_cell": 20,
                  "bootstrap": {"seed": 20261027, "resamples": 10000, "unit": "clip"}},
        "statement": ("Frozen before the evaluation half's anchors are drawn. Development results (C1b) were scored "
                      "earlier under the same rules; no rule, threshold or reference was changed after them."),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("build", "verify"))
    ap.add_argument("--c3e", type=Path, required=True)
    a = ap.parse_args()
    m = build(a.c3e)
    if a.mode == "build":
        if MANIFEST.exists():
            raise SystemExit(f"{MANIFEST} exists: a frozen manifest is never rewritten")
        MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"written": str(MANIFEST), "sha256": sha(MANIFEST)}))
        return 0
    old = json.loads(MANIFEST.read_text(encoding="utf-8"))
    drift = [k for k in old if old[k] != m[k]]
    print(json.dumps({"ok": not drift, "drift": drift, "manifest_sha256": sha(MANIFEST)}))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
