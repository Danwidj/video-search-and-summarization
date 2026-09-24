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
from eval_gt import Result, compare_incident_fields, prf1, resolve_holder, run_evaluation, score_matched_pair

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


# --------------------------------------------------------------------------- #
# resolve_holder - never influences match/no-match, three outcomes only
# --------------------------------------------------------------------------- #


def test_resolve_holder_correct_when_resolved_entity_matches_gt_holder():
    model_instrument = {"instrument_id": "I1", "entity_id": "E1"}
    gt_instrument = {"instrument_id": "GI1", "entity_id": "GE1"}
    entity_matches = [{"entity_id": "E1", "gt_entity_id": "GE1", "similarity_score": 0.9}]
    result = resolve_holder(model_instrument, gt_instrument, entity_matches)
    assert result == {
        "expected": "GE1",
        "predicted": "E1",
        "resolved_gt_entity_id": "GE1",
        "status": "correct",
    }


def test_resolve_holder_incorrect_when_resolved_entity_differs():
    model_instrument = {"instrument_id": "I1", "entity_id": "E2"}
    gt_instrument = {"instrument_id": "GI1", "entity_id": "GE1"}
    # E2 matched to GE2, not GE1 - the instrument's real GT holder.
    entity_matches = [{"entity_id": "E2", "gt_entity_id": "GE2", "similarity_score": 0.9}]
    result = resolve_holder(model_instrument, gt_instrument, entity_matches)
    assert result["status"] == "incorrect"
    assert result["resolved_gt_entity_id"] == "GE2"


def test_resolve_holder_unresolved_when_either_side_has_no_holder():
    entity_matches = [{"entity_id": "E1", "gt_entity_id": "GE1", "similarity_score": 0.9}]
    assert resolve_holder({"entity_id": None}, {"entity_id": "GE1"}, entity_matches)["status"] == "unresolved"
    assert resolve_holder({"entity_id": "E1"}, {"entity_id": None}, entity_matches)["status"] == "unresolved"


def test_resolve_holder_unresolved_when_holder_entity_itself_unmatched():
    # E9 (the model instrument's holder) never appears in the accepted entity matches.
    model_instrument = {"entity_id": "E9"}
    gt_instrument = {"entity_id": "GE1"}
    entity_matches = [{"entity_id": "E1", "gt_entity_id": "GE1", "similarity_score": 0.9}]
    result = resolve_holder(model_instrument, gt_instrument, entity_matches)
    assert result["status"] == "unresolved"
    assert "resolved_gt_entity_id" not in result


# --------------------------------------------------------------------------- #
# score_matched_pair - per-kind attribute scoring, additive over matching.py
# --------------------------------------------------------------------------- #


def test_score_matched_pair_instruments_includes_threat_level_and_holder():
    model_row = {"entity_id": "E1", "name": "crowbar", "description": "metal crowbar", "threat_level": 3}
    gt_row = {"entity_id": "GE1", "name": "crowbar", "description": "metal crowbar", "threat_level": 3}
    entity_matches = [{"entity_id": "E1", "gt_entity_id": "GE1", "similarity_score": 1.0}]

    with patch.object(eval_gt, "judge_description_similarity", return_value=Result(ok=True, data=0.9)):
        scores = score_matched_pair("instruments", model_row, gt_row, entity_matches=entity_matches)

    assert scores["threat_level"] == {"expected": 3, "predicted": 3, "pass": True}
    assert scores["holder"]["status"] == "correct"
    assert scores["name"]["score"] == pytest.approx(0.9)
    assert scores["description"]["score"] == pytest.approx(0.9)


def test_score_matched_pair_instruments_threat_level_mismatch():
    model_row = {"threat_level": 2}
    gt_row = {"threat_level": 4}
    with patch.object(eval_gt, "judge_description_similarity", return_value=Result(ok=True, data=1.0)):
        scores = score_matched_pair("instruments", model_row, gt_row, entity_matches=[])
    assert scores["threat_level"] == {"expected": 4, "predicted": 2, "pass": False}


def test_score_matched_pair_entities_scores_type_and_description():
    model_row = {"type": "human", "description": "a person in a red jacket"}
    gt_row = {"type": "Human", "description": "an individual wearing a red jacket"}
    with patch.object(eval_gt, "judge_description_similarity", return_value=Result(ok=True, data=0.8)):
        scores = score_matched_pair("entities", model_row, gt_row)
    assert scores["type"]["pass"] is True  # case-insensitive, like compare_incident_fields' type check
    assert scores["description"]["score"] == pytest.approx(0.8)


# --------------------------------------------------------------------------- #
# judge_description_similarity retry - parse failures only, same request every
# attempt, never retries a network/HTTP/missing-base-url failure.
# --------------------------------------------------------------------------- #


class _FakeHttpResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json_body = json_body
        self.text = str(json_body)

    def json(self):
        return self._json_body


def _chat_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def test_judge_retries_on_parse_failure_then_succeeds(monkeypatch):
    monkeypatch.setenv("INCIDENT_LLM_BASE_URL", "http://fake-judge/v1")
    responses = [
        _FakeHttpResponse(200, _chat_body("I decline to answer that.")),  # attempt 1: unparseable
        _FakeHttpResponse(200, _chat_body('{"score": 0.8, "reasoning": "close enough"}')),  # attempt 2: parses
    ]
    with patch("httpx.post", side_effect=responses) as mock_post:
        result = eval_gt.judge_description_similarity("a", "b", max_retries=2)
    assert result.ok is True
    assert result.data == pytest.approx(0.8)
    assert mock_post.call_count == 2


def test_judge_gives_up_after_exhausting_retries():
    responses = [_FakeHttpResponse(200, _chat_body("not a score, sorry")) for _ in range(3)]
    with (
        patch("config.llm_base_url", return_value="http://fake-judge/v1"),
        patch("httpx.post", side_effect=responses) as mock_post,
    ):
        result = eval_gt.judge_description_similarity("a", "b", max_retries=2)
    assert result.ok is False
    assert "could not extract a score" in result.error
    assert mock_post.call_count == 3  # 1 initial + 2 retries, no more


def test_judge_does_not_retry_http_error():
    responses = [_FakeHttpResponse(401, {"error": "unauthorized"})]
    with (
        patch("config.llm_base_url", return_value="http://fake-judge/v1"),
        patch("httpx.post", side_effect=responses) as mock_post,
    ):
        result = eval_gt.judge_description_similarity("a", "b", max_retries=2)
    assert result.ok is False
    assert result.status_code == 401
    assert mock_post.call_count == 1  # never retried


def test_judge_does_not_retry_missing_base_url(monkeypatch):
    monkeypatch.delenv("INCIDENT_LLM_BASE_URL", raising=False)
    with patch("httpx.post") as mock_post:
        result = eval_gt.judge_description_similarity("a", "b", max_retries=2)
    assert result.ok is False
    assert "INCIDENT_LLM_BASE_URL is not set" in result.error
    mock_post.assert_not_called()


def test_judge_succeeds_on_first_attempt_makes_exactly_one_call():
    responses = [_FakeHttpResponse(200, _chat_body('{"score": 0.5, "reasoning": "ok"}'))]
    with (
        patch("config.llm_base_url", return_value="http://fake-judge/v1"),
        patch("httpx.post", side_effect=responses) as mock_post,
    ):
        result = eval_gt.judge_description_similarity("a", "b", max_retries=2)
    assert result.ok is True
    assert mock_post.call_count == 1


def test_run_evaluation_attaches_attribute_scores_to_instrument_matches(incident_db: IncidentDB):
    incident_id, model_run_id = "Burglary002", "MR-1"
    incident_db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4")
    incident_db.insert_model_run(model_run_id, model_name="incident-vlm", prompt_version="p1")
    incident_db.insert_incident(incident_id, model_run_id, fields={"type": "burglary", "severity_level": 3})
    incident_db.insert_gt_incident(incident_id, fields={"type": "burglary", "severity_level": 3})

    incident_db.add_incident_entity(incident_id, model_run_id, entity_id="E1", type="human", description="a tall man")
    incident_db.add_gt_entity(incident_id, entity_id="GE1", type="human", description="a tall man")

    incident_db.add_incident_instrument(
        incident_id, model_run_id, instrument_id="I1", entity_id="E1", name="crowbar",
        description="metal crowbar", threat_level=3,
    )
    incident_db.add_gt_instrument(
        incident_id, instrument_id="GI1", entity_id="GE1", name="crowbar",
        description="metal crowbar", threat_level=3,
    )

    with (
        patch.object(matching, "embed_texts", side_effect=_fake_embed),
        patch.object(eval_gt, "judge_description_similarity", return_value=Result(ok=True, data=0.95)),
    ):
        result = run_evaluation(incident_db, incident_id, model_run_id)

    assert len(result.matches["instruments"]) == 1
    attr = result.matches["instruments"][0]["attribute_scores"]
    assert attr["threat_level"] == {"expected": 3, "predicted": 3, "pass": True}
    assert attr["holder"]["status"] == "correct"
    assert attr["name"]["score"] == pytest.approx(0.95)
