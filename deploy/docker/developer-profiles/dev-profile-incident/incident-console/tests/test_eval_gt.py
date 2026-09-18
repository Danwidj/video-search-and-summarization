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

"""Tier 1 GT evaluation: field comparison, P/R/F1, and end-to-end orchestration."""

from __future__ import annotations

import re
from collections import Counter
from unittest.mock import patch

import pytest

import embed_client
import eval_gt
import matching
from db import IncidentDB
from eval_gt import Result, compare_incident_fields, prf1, run_evaluation

# --------------------------------------------------------------------------- #
# compare_incident_fields
# --------------------------------------------------------------------------- #


def test_compare_incident_fields_exact_matches():
    gt = {
        "type": "Burglary",
        "severity_level": 3,
        "start_timestamp": "00:00:10",
        "end_timestamp": "00:00:20",
        "duration": 10,
    }
    model = {
        "type": "burglary",
        "severity_level": 3,
        "start_timestamp": "00:00:10",
        "end_timestamp": "00:00:20",
        "duration": 10,
    }
    fields = compare_incident_fields(gt, model)
    assert fields["type"]["pass"] is True
    assert fields["severity_level"]["pass"] is True
    assert fields["start_timestamp"]["pass"] is True
    assert fields["end_timestamp"]["pass"] is True
    assert fields["duration"]["pass"] is True


def test_compare_incident_fields_type_mismatch_and_missing_severity():
    gt = {"type": "burglary", "severity_level": 3}
    model = {"type": "explosion", "severity_level": None}
    fields = compare_incident_fields(gt, model)
    assert fields["type"]["pass"] is False
    assert fields["severity_level"]["pass"] is False


def test_compare_incident_fields_timestamp_tolerance_boundary_inside():
    gt = {"start_timestamp": "00:00:10"}
    model = {"start_timestamp": "00:00:15"}  # exactly 5s off; default tolerance is 5
    fields = compare_incident_fields(gt, model)
    assert fields["start_timestamp"]["pass"] is True


def test_compare_incident_fields_timestamp_tolerance_boundary_outside():
    gt = {"start_timestamp": "00:00:10"}
    model = {"start_timestamp": "00:00:16"}  # 6s off; outside default tolerance
    fields = compare_incident_fields(gt, model)
    assert fields["start_timestamp"]["pass"] is False


def test_compare_incident_fields_duration_tolerance():
    gt = {"duration": 100}
    model_within = {"duration": 103}
    model_outside = {"duration": 200}
    assert compare_incident_fields(gt, model_within)["duration"]["pass"] is True
    assert compare_incident_fields(gt, model_outside)["duration"]["pass"] is False


def test_compare_incident_fields_leaves_description_score_for_caller():
    gt = {"description": "a person forces open a door"}
    model = {"description": "someone pried open a door"}
    fields = compare_incident_fields(gt, model)
    assert fields["description"]["expected"] == gt["description"]
    assert fields["description"]["predicted"] == model["description"]
    assert "score" not in fields["description"]


# --------------------------------------------------------------------------- #
# prf1
# --------------------------------------------------------------------------- #


def test_prf1_standard_case():
    result = prf1(tp=3, fp=1, fn=1)
    assert result["precision"] == pytest.approx(0.75)
    assert result["recall"] == pytest.approx(0.75)
    assert result["f1"] == pytest.approx(0.75)


def test_prf1_all_zero_is_divide_by_zero_safe():
    result = prf1(tp=0, fp=0, fn=0)
    assert result == {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}


# --------------------------------------------------------------------------- #
# run_evaluation (end to end against the hermetic SQLite fixture)
# --------------------------------------------------------------------------- #


def _fake_embed(texts):
    """Deterministic bag-of-words term-count vectors, no network (see test_matching.py)."""
    tokenized = [re.findall(r"[a-z']+", text.lower()) for text in texts]
    vocab = sorted({word for tokens in tokenized for word in tokens})
    vectors = [[float(Counter(tokens).get(word, 0)) for word in vocab] for tokens in tokenized]
    return embed_client.Result(ok=True, data=vectors)


def _seed_evaluation_fixture(db: IncidentDB, *, incident_id="Burglary001", model_run_id="MR-1"):
    db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4")
    db.insert_model_run(model_run_id, model_name="incident-vlm", prompt_version="p1")
    db.insert_incident(
        incident_id,
        model_run_id,
        fields={
            "type": "burglary",
            "severity_level": 3,
            "start_timestamp": "00:00:10",
            "end_timestamp": "00:00:20",
            "duration": 10,
            "description": "a person forces open a side door and takes a cash box",
        },
    )
    db.insert_gt_incident(
        incident_id,
        fields={
            "type": "burglary",
            "severity_level": 3,
            "start_timestamp": "00:00:10",
            "end_timestamp": "00:00:20",
            "duration": 10,
            "description": "an individual pries open a door and removes a cash box",
        },
    )

    # entities: one exact-ish match (TP)
    db.add_incident_entity(
        incident_id, model_run_id, entity_id="E1", type="human", description="person in dark clothing"
    )
    db.add_gt_entity(incident_id, entity_id="GE1", type="human", description="person in dark clothing")

    # instruments: one model-only row -> FP (no GT instrument at all)
    db.add_incident_instrument(
        incident_id, model_run_id, instrument_id="I1", name="crowbar", description="metal crowbar"
    )

    # assets: one GT-only row -> FN (model omits it)
    db.add_gt_asset(incident_id, asset_id="GA1", name="atm", description="atm carried away")

    return incident_id, model_run_id


def test_run_evaluation_end_to_end(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_evaluation_fixture(incident_db)

    with (
        patch.object(matching, "embed_texts", side_effect=_fake_embed),
        patch.object(eval_gt, "judge_description_similarity", return_value=Result(ok=True, data=0.85)),
    ):
        result = run_evaluation(incident_db, incident_id, model_run_id)

    assert result.incident_id == incident_id
    assert result.fields["type"]["pass"] is True
    assert result.fields["severity_level"]["pass"] is True
    assert result.fields["start_timestamp"]["pass"] is True
    assert result.description_score == pytest.approx(0.85)
    assert result.fields["description"]["pass"] is True

    # entities: 1 TP, 0 FP, 0 FN
    assert result.counts["entities"] == {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    # instruments: 0 TP, 1 FP (model-only crowbar), 0 FN
    assert result.counts["instruments"]["tp"] == 0
    assert result.counts["instruments"]["fp"] == 1
    assert result.counts["instruments"]["fn"] == 0
    # assets: 0 TP, 0 FP, 1 FN (GT-only atm)
    assert result.counts["assets"]["tp"] == 0
    assert result.counts["assets"]["fp"] == 0
    assert result.counts["assets"]["fn"] == 1

    assert [r["instrument_id"] for r in result.unmatched["instruments"]["model"]] == ["I1"]
    assert [r["asset_id"] for r in result.unmatched["assets"]["gt"]] == ["GA1"]


def test_run_evaluation_description_judge_failure_fails_soft(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_evaluation_fixture(incident_db)

    with (
        patch.object(matching, "embed_texts", side_effect=_fake_embed),
        patch.object(eval_gt, "judge_description_similarity", return_value=Result(ok=False, error="LLM unreachable")),
    ):
        result = run_evaluation(incident_db, incident_id, model_run_id)

    assert result.description_score is None
    assert result.description_error == "LLM unreachable"
    assert result.fields["description"]["pass"] is False
