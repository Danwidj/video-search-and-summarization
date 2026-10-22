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

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_run_lib import coerce_int_or_none, model_run_id_for, safe_model_id, score_matches_summary  # noqa: E402


def test_model_run_id_for_known_models_fits_db_column():
    for model in [
        "nvidia/cosmos-3-nano-reasoner",
        "nvidia/cosmos-3-super-reasoner",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    ]:
        run_id = model_run_id_for(model)
        assert len(run_id) <= 20


def test_model_run_id_for_all_three_are_distinct():
    ids = {
        model_run_id_for(m)
        for m in [
            "nvidia/cosmos-3-nano-reasoner",
            "nvidia/cosmos-3-super-reasoner",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        ]
    }
    assert len(ids) == 3


def test_model_run_id_for_unknown_model_raises():
    with pytest.raises(ValueError):
        model_run_id_for("nvidia/some-new-model")


def test_safe_model_id_replaces_slash():
    assert safe_model_id("nvidia/cosmos-3-nano-reasoner") == "nvidia_cosmos-3-nano-reasoner"


@dataclass
class _FakeEvalResult:
    matches: dict = field(default_factory=dict)
    unmatched: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)


def test_score_matches_summary_assembles_expected_shape():
    result = _FakeEvalResult(
        matches={"entities": [{"entity_id": "E1", "attribute_scores": {}}]},
        unmatched={"entities": {"model": [{"entity_id": "E2"}], "gt": [{"entity_id": "GE9"}]}},
        counts={"entities": {"tp": 1, "fp": 1, "fn": 1}},
    )
    summary = score_matches_summary(result, "entities")
    assert summary["matches"] == [{"entity_id": "E1", "attribute_scores": {}}]
    assert summary["unmatched_model"] == [{"entity_id": "E2"}]
    assert summary["unmatched_gt"] == [{"entity_id": "GE9"}]
    assert summary["counts"] == {"tp": 1, "fp": 1, "fn": 1}


def test_score_matches_summary_missing_kind_defaults_empty():
    result = _FakeEvalResult()
    summary = score_matches_summary(result, "assets")
    assert summary == {"matches": [], "unmatched_model": [], "unmatched_gt": [], "counts": {}}


# --------------------------------------------------------------------------- #
# coerce_int_or_none - regression coverage for the live PostgREST failure:
# "invalid input syntax for type integer: \"6.0\"" on a bare JSON float.
# --------------------------------------------------------------------------- #


def test_coerce_int_or_none_passes_through_int():
    assert coerce_int_or_none(6) == 6


def test_coerce_int_or_none_converts_whole_float():
    assert coerce_int_or_none(6.0) == 6


def test_coerce_int_or_none_truncates_fractional_float():
    assert coerce_int_or_none(6.9) == 6


def test_coerce_int_or_none_none_stays_none():
    assert coerce_int_or_none(None) is None


def test_coerce_int_or_none_numeric_string():
    assert coerce_int_or_none("6") == 6


def test_coerce_int_or_none_numeric_string_with_decimal():
    assert coerce_int_or_none("6.0") == 6


def test_coerce_int_or_none_unparseable_returns_none_not_raise():
    assert coerce_int_or_none("not a number") is None
