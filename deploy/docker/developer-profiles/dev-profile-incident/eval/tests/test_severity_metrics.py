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

"""Severity reporting extension (methodology v1.3): MAE and friends, never a change to an existing score."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import experiment_selection as es  # noqa: E402
import extraction_stats  # noqa: E402
import severity_metrics as sm  # noqa: E402


def _run(incident_id, expected, predicted, *, outcome="scored", repeat=1):
    scores = {} if outcome in extraction_stats.NO_MODEL_OUTPUT else {
        "severity_level": {"expected": expected, "predicted": predicted, "pass": predicted == expected}}
    return {"incident_id": incident_id, "repeat": repeat, "outcome": outcome, "incident_field_scores": scores}


def test_mae_and_signed_error_over_valid_predictions_only():
    runs = [_run("A", 3, 4), _run("B", 3, 5), _run("C", 2, 2), _run("D", 4, None, outcome="contract_invalid"),
            _run("E", 3, None, outcome="timeout")]
    s = sm.summarise(runs)
    assert s["valid"] == 3 and s["attempted"] == 5 and s["coverage"] == 0.6
    assert s["mae"] == round(3 / 3, 4) and s["mean_signed_error"] == 1.0  # (1 + 2 + 0) / 3
    assert s["exact"] == round(1 / 3, 4) and s["within_one"] == round(2 / 3, 4)
    assert s["failure_categories"] == {"no_predicted_level": 1, "no_model_output": 1}
    assert (s["over_rated"], s["under_rated"]) == (2, 0)


def test_failures_are_never_given_a_severity_value():
    s = sm.summarise([_run("A", 3, None, outcome="rate_limited"), _run("B", 3, None, outcome="contract_invalid")])
    assert s["valid"] == 0 and s["mae"] is None and s["mean_signed_error"] is None


def test_paired_difference_averages_repeats_per_video():
    base = [_run("A", 3, 5, repeat=1), _run("A", 3, 4, repeat=2), _run("B", 2, 2), _run("C", 1, 3)]
    cand = [_run("A", 3, 3, repeat=1), _run("A", 3, 4, repeat=2), _run("B", 2, 3)]  # C has no valid run here
    p = sm.paired(base, cand, resamples=500, seed=1)
    assert p["pairs"] == 2  # A and B
    # A: base 1.5 -> cand 0.5 (diff -1.0); B: 0 -> 1 (+1.0)
    assert p["mae_difference"] == 0.0 and p["baseline_mae_on_pairs"] == 0.75
    assert p["mae_difference_ci95"][0] <= 0.0 <= p["mae_difference_ci95"][1]


def test_the_extension_changes_no_existing_score():
    runs = [_run("A", 3, 4), _run("B", 2, 2)]
    before = copy.deepcopy(runs)
    sm.summarise(runs)
    sm.paired(runs, runs, resamples=10)
    assert runs == before
    assert extraction_stats.severity_analysis(runs)["exact"] == 0.5  # the existing definition is untouched
    assert "severity_level" in es.INCIDENT_SCORES  # D9 still uses the exact-match severity score
