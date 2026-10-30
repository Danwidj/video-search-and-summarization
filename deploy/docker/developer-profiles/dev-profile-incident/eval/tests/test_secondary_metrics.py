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

"""Offline secondary metrics and the near-duplicate overlap rule. Hermetic: synthetic records, no video."""

from __future__ import annotations

import sys
from pathlib import Path

import secondary_metrics as sm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_near_duplicates as nd  # noqa: E402


def _video(category, *, passed=True, counts=None, matches=None, outcome="scored", instruments=None):
    fields = {f: {"pass": passed} for f in ("type", "severity_level", "start_timestamp", "end_timestamp", "duration",
                                            "description")}
    return {"category": category, "outcome": outcome, "incident_field_scores": fields,
            "entities": {"counts": counts or {"tp": 0, "fp": 0, "fn": 0}, "matches": matches or []},
            "instruments": instruments or {"counts": {"tp": 0, "fp": 0, "fn": 0}, "matches": []},
            "assets": {"counts": {"tp": 0, "fp": 0, "fn": 0}, "matches": []}}


def test_macro_is_the_category_mean_and_micro_the_video_mean():
    videos = [_video("A"), _video("A"), _video("A", passed=False), _video("B", passed=False)]
    row = sm.macro_accuracy(videos)["type"]
    assert row["micro"] == 0.5 and row["macro"] == round((2 / 3 + 0.0) / 2, 4)


def test_a_failed_request_is_left_out_and_both_empty_is_excluded_from_the_per_video_mean():
    videos = [_video("A", counts={"tp": 1, "fp": 1, "fn": 0}), _video("A"),
              _video("A", counts={"tp": 0, "fp": 0, "fn": 5}, outcome="timeout")]
    items = sm.item_means(videos)["entities"]
    assert items["pooled"]["tp"] == 1 and items["pooled"]["fn"] == 0  # the timeout run is not counted
    assert items["per_video_n"] == 1 and items["both_empty_excluded"] == 1
    assert items["per_video_mean_f1"] == round(2 / 3, 4)


def test_a_stricter_threshold_only_drops_saved_matches():
    matches = [{"similarity_score": 0.45}, {"similarity_score": 0.8}]
    videos = [_video("A", counts={"tp": 2, "fp": 1, "fn": 1}, matches=matches)]
    row = sm.stricter_threshold(videos, thresholds=(0.5, 0.9))
    assert row["0.50"]["entities"] == sm._prf(1, 2, 2)
    assert row["0.90"]["entities"]["tp"] == 0 and row["0.90"]["entities"]["fp"] == 3


def test_instrument_threat_and_holder_on_matched_instruments():
    match = {"attribute_scores": {"threat_level": {"expected": 3, "predicted": 2},
                                  "holder": {"expected": "E1", "status": "correct"}}}
    other = {"attribute_scores": {"threat_level": {"expected": 1, "predicted": 4},
                                  "holder": {"expected": None, "status": "unresolved"}}}
    videos = [_video("A", instruments={"counts": {"tp": 2, "fp": 0, "fn": 0}, "matches": [match, other]})]
    out = sm.instrument_attributes(videos)
    assert out["threat_exact"] == 0.0 and out["threat_within_one"] == 0.5
    assert out["holder"]["correct"] == 1 and out["holder"]["ground_truth_without_holder"] == 1
    assert out["holder_accuracy"] == 1.0


def test_near_duplicate_overlap_is_the_shorter_sides_matching_share():
    a, b = [0b0, 0b1111, (1 << 63)], [0b1, (1 << 40) - 1]
    share, hits = nd.overlap(a, b, max_distance=4)
    assert (share, hits) == (0.5, 1)  # b is shorter: 0b1 is 1 bit from 0b0; the 40-bit hash matches nothing
    assert nd.overlap(a, [0b1, 0b111], max_distance=4) == (1.0, 2)
    assert nd.overlap([], b, 4) == (0.0, 0)
