# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The exploratory threshold analysis: boundary rule, frozen rate unchanged, reviewers blinded."""

import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[2] / "scripts" / "v2_description_threshold_sensitivity.py"
spec = importlib.util.spec_from_file_location("sens", path)
sens = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sens)


def item(score, subject="nano-direct", clip="Animal001", repeat=1):
    return {"score": score, "subject": subject, "clip": clip, "repeat": repeat, "category": "Animal", "expected": f"gt {clip}",
            "predicted": f"p {score} {repeat}", "type_pass": True}


def test_boundary_is_inclusive_like_the_frozen_rule():
    assert sens.passes(0.5, 0.5) and sens.passes(0.4, 0.4) and not sens.passes(0.39, 0.4)


def test_rate_counts_within_the_given_denominator():
    assert sens.rate([item(0.4), item(0.5), item(0.0), item(0.6)], 0.5) == 0.5


def test_frozen_threshold_is_in_the_grid_and_unchanged():
    assert sens.FROZEN == 0.50 and 0.50 in sens.THRESHOLDS and 0.40 in sens.THRESHOLDS


def test_review_sheet_hides_model_and_score():
    items = [item(s / 20, subject=sub, clip=f"Animal{s:03d}", repeat=r) for s in range(21) for sub in sens.MODELS for r in (1, 2)]
    sheet, key = sens.review_sample(items)
    assert sheet and len(sheet) == len(key)
    assert not {"score", "subject", "clip", "repeat", "model"} & set(sheet[0])
    assert {k["review_id"] for k in key} == {s["review_id"] for s in sheet}
