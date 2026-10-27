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

"""evaluation-methodology-v1.0: pinned instruments, scoring failures never become zeros, reproducible statistics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_aggregate  # noqa: E402
import eval_gt  # noqa: E402
import eval_run  # noqa: E402
import extraction_stats as xs  # noqa: E402
import matching  # noqa: E402
import methodology  # noqa: E402
from embed_client import Result as EmbedResult  # noqa: E402
from eval_run_lib import EvaluatorDependencyError, check_scoring_complete  # noqa: E402

LEGACY_JUDGE_PROMPT = """INCIDENT_JUDGE_REQUEST
You are scoring whether two incident descriptions describe the same underlying
event, allowing for different wording, phrasing, and level of detail. Score
0.0 (unrelated events) to 1.0 (semantically equivalent). Respond with a JSON
object: {"score": <float 0.0-1.0>, "reasoning": "<one sentence>"}."""


class _Response:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _score(value: float) -> _Response:
    return _Response(200, {"choices": [{"message": {"content": json.dumps({"score": value})}}]})


# --- pins -------------------------------------------------------------------------------


def test_judge_prompt_file_is_the_prompt_every_earlier_result_used():
    assert methodology.judge_prompt() == LEGACY_JUDGE_PROMPT
    assert eval_gt._JUDGE_SYSTEM_PROMPT == LEGACY_JUDGE_PROMPT
    assert methodology.judge_prompt_sha256() == "093ddcd5b42be719773ed88662ae8aef136b576aa22bb73f7629a7a5c29a54fd"


def test_judge_request_uses_the_pinned_model_prompt_and_settings(monkeypatch):
    monkeypatch.setenv("INCIDENT_LLM_BASE_URL", "http://judge.example/v1")
    sent = {}

    def post(url, *, json, headers, timeout):
        sent.update(json)
        return _score(0.8)

    with patch.object(eval_gt.httpx, "post", side_effect=post):
        result = eval_gt.judge_description_similarity("a", "b")
    assert result.ok and result.data == 0.8
    assert sent["model"] == methodology.JUDGE_MODEL == "nvidia/nemotron-3-nano-30b-a3b"
    assert sent["temperature"] == 0.0
    assert sent["messages"][0] == {"role": "system", "content": LEGACY_JUDGE_PROMPT}


@pytest.mark.parametrize(("configured", "mismatch"), [("", False), ("nvidia/nemotron-3-nano-30b-a3b", False),
                                                      ("incident-judge", True), ("gpt-4o", True)])
def test_a_different_judge_model_is_refused(monkeypatch, configured, mismatch):
    monkeypatch.setenv("INCIDENT_JUDGE_MODEL", configured)
    assert (methodology.judge_model_mismatch() is not None) is mismatch


def test_run_refuses_to_start_with_a_different_judge(monkeypatch):
    monkeypatch.setenv("INCIDENT_JUDGE_MODEL", "some-other-judge")
    with pytest.raises(EvaluatorDependencyError, match="pins the judge"):
        eval_run.run(models=["m"], categories=None, limit=None, incident_only=True)


def test_methodology_record_names_every_pin():
    record = methodology.record()
    assert record["methodology_version"] == "evaluation-methodology-v1.0"
    assert record["judge"]["prompt_sha256"] == methodology.judge_prompt_sha256()
    assert record["embedding"] == {"model": "sentence-transformers/all-MiniLM-L6-v2", "base_url": "http://127.0.0.1:8811/v1"}
    assert (record["match_threshold"], record["timestamp_tolerance_s"]) == (0.75, 5)
    assert record["bootstrap"]["seed"] == methodology.BOOTSTRAP_SEED
    assert eval_run.FROZEN_EMBEDDING_MODEL == record["embedding"]["model"]


# --- transient judge failures are retried; remaining failures are errors, not scores ---


def test_transient_judge_failures_are_retried_with_the_same_request(monkeypatch):
    monkeypatch.setenv("INCIDENT_LLM_BASE_URL", "http://judge.example/v1")
    sleeps, bodies = [], []
    responses = iter([_Response(503, text="busy"), _Response(429, text="slow down"), _score(0.6)])

    def post(url, *, json, headers, timeout):
        bodies.append(json)
        return next(responses)

    with patch.object(eval_gt.httpx, "post", side_effect=post), patch.object(eval_gt, "_sleep", side_effect=sleeps.append):
        result = eval_gt.judge_description_similarity("a", "b")
    assert result.ok and result.data == 0.6
    assert sleeps == list(methodology.JUDGE_RETRY_BACKOFF_SECONDS) and all(b == bodies[0] for b in bodies)


@pytest.mark.parametrize("response", [_Response(400, text="bad request"), _Response(401, text="no")])
def test_client_errors_are_not_retried(monkeypatch, response):
    monkeypatch.setenv("INCIDENT_LLM_BASE_URL", "http://judge.example/v1")
    with patch.object(eval_gt.httpx, "post", return_value=response) as post, patch.object(eval_gt, "_sleep") as sleep:
        result = eval_gt.judge_description_similarity("a", "b")
    assert not result.ok and post.call_count == 1 and sleep.call_count == 0


def test_a_missing_judge_endpoint_is_not_retried(monkeypatch):
    monkeypatch.delenv("INCIDENT_LLM_BASE_URL", raising=False)
    with patch.object(eval_gt, "_sleep") as sleep:
        result = eval_gt.judge_description_similarity("a", "b")
    assert not result.ok and "INCIDENT_LLM_BASE_URL" in result.error and sleep.call_count == 0


def test_an_item_judge_failure_is_unscored_not_failed():
    with patch.object(eval_gt, "judge_description_similarity", return_value=eval_gt.Result(ok=False, error="down")):
        score = eval_gt._judged_field_score("a red jacket", "red coat")
    assert score["pass"] is None and score["score"] is None and score["error"] == "down"


# --- the embedder failing is a scoring error, never zero matches -------------------------


def _seed(db, incident_id="Burglary001", run="MR-1"):
    db.upsert_video(incident_id, filepath=f"anomaly/burglary/{incident_id}_x264.mp4")
    db.insert_model_run(run, model_name="m")
    db.insert_incident(incident_id, run, fields={"type": "burglary", "description": "A man forces a door."})
    db.insert_gt_incident(incident_id, fields={"type": "burglary", "description": "A man forces a door."})
    db.add_incident_entity(incident_id, run, entity_id="E1", type="human", description="man in a red jacket")
    db.add_gt_entity(incident_id, entity_id="E1", type="human", description="man in a red jacket")
    return incident_id, run


def test_embedder_failure_leaves_the_kind_unscored_and_stops_the_run(incident_db):
    incident_id, run = _seed(incident_db)
    with (
        patch.object(matching, "embed_texts", return_value=EmbedResult(ok=False, error="connection refused")),
        patch.object(eval_gt, "judge_description_similarity", return_value=eval_gt.Result(ok=True, data=0.9)),
    ):
        result = eval_gt.run_evaluation(incident_db, incident_id, run)
    assert result.counts["entities"] is None
    assert result.scoring_errors == [{"field": "entities.matching", "error": "entities: connection refused"}]
    assert result.counts["instruments"]["fn"] == 0  # nothing on either side: scored, no embedder call needed
    with pytest.raises(EvaluatorDependencyError, match="could not be scored"):
        check_scoring_complete(result)


def test_offline_and_database_scoring_agree_on_failures(incident_db):
    from offline_store import OfflineEvalStore

    outcomes = []
    for store in (incident_db, OfflineEvalStore()):
        incident_id, run = _seed(store)
        with (
            patch.object(matching, "embed_texts", return_value=EmbedResult(ok=False, error="down")),
            patch.object(eval_gt, "judge_description_similarity", return_value=eval_gt.Result(ok=False, error="judge down")),
        ):
            outcomes.append(eval_gt.run_evaluation(store, incident_id, run))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0].fields["description"]["pass"] is None


# --- aggregation: unscored values are excluded and counted; versions are not mixed ---


def _video(incident_id, *, type_pass=True, severity=(3, 3), description_pass=True, outcome="scored", counts=None,
           instruments=None):
    return {
        "filename": f"{incident_id}.mp4", "incident_id": incident_id, "outcome": outcome,
        "p1_raw": {"ok": outcome not in xs.NO_MODEL_OUTPUT, "contract_ok": True, "core_ok": True},
        "rp1_report": {"ok": True},
        "incident_field_scores": {
            "type": {"pass": type_pass},
            "severity_level": {"expected": severity[0], "predicted": severity[1], "pass": severity[0] == severity[1]},
            "start_timestamp": {"expected": 1, "predicted": 2, "pass": True},
            "end_timestamp": {"expected": 9, "predicted": 9, "pass": True},
            "duration": {"expected": 8, "predicted": 7, "pass": True},
            "description": {"score": None if description_pass is None else 0.8, "pass": description_pass},
        },
        "entities": {"matches": [], "counts": counts if counts is not None else {"tp": 1, "fp": 0, "fn": 0}},
        "instruments": {"matches": instruments or [], "counts": {"tp": len(instruments or []), "fp": 0, "fn": 0}},
        "assets": {"matches": [], "counts": {"tp": 0, "fp": 0, "fn": 0}},
    }


def test_unscored_values_are_excluded_and_counted_not_zero():
    videos = [_video("A1"), _video("A2", type_pass=None, description_pass=None), _video("A3", type_pass=False)]
    videos[1]["entities"]["counts"] = None
    agg = eval_aggregate.aggregate_one({"videos": videos})
    assert agg["incident_field_accuracy"]["type"] == 50.0  # 1 of 2 scored, not 1 of 3
    assert agg["unscored"]["fields"]["type"] == 1 and agg["unscored"]["fields"]["description"] == 1
    assert agg["unscored"]["kinds"]["entities"] == 1 and agg["entities"]["tp"] == 2
    intervals = xs.field_intervals(videos)
    assert intervals["type"] == {**intervals["type"], "n": 2, "unscored": 1, "accuracy": 0.5}


def test_no_model_output_is_excluded_but_an_invalid_output_is_a_miss():
    videos = [_video("A1"), _video("A2", type_pass=False, outcome="contract_invalid"),
              _video("A3", type_pass=False, outcome="timeout")]
    intervals = xs.field_intervals(videos)["type"]
    assert (intervals["n"], intervals["no_model_output"], intervals["accuracy"]) == (2, 1, 0.5)


def test_severity_analysis_reports_within_one_bias_and_confusion():
    videos = [_video("A1", severity=(3, 3)), _video("A2", severity=(3, 4)), _video("A3", severity=(2, 4)),
              _video("A4", severity=(5, None))]
    analysis = xs.severity_analysis(videos)
    assert (analysis["n"], analysis["exact"], analysis["within_one"]) == (4, 0.25, 0.5)
    assert analysis["mean_signed_error"] == 1.0  # (0 + 1 + 2) / 3 predicted
    assert analysis["confusion"]["3"]["4"] == 1 and analysis["confusion"]["5"]["missing"] == 1


def test_instrument_threat_and_holder_rates():
    instruments = [
        {"attribute_scores": {"threat_level": {"expected": 3, "predicted": 4}, "holder": {"status": "correct"}}},
        {"attribute_scores": {"threat_level": {"expected": 4, "predicted": 4}, "holder": {"status": "incorrect"}}},
        {"attribute_scores": {"threat_level": {"expected": 2, "predicted": 5}, "holder": {"status": "unresolved"}}},
    ]
    attributes = xs.instrument_attributes([_video("A1", instruments=instruments)])
    assert attributes["threat_level"] == {"n": 3, "exact": round(1 / 3, 4), "within_one": round(2 / 3, 4)}
    assert attributes["holder"] == {"correct": 1, "incorrect": 1, "unresolved": 1, "accuracy": 0.5}


def test_paired_difference_uses_the_same_videos_on_both_sides():
    a = [_video("A1", type_pass=False), _video("A2", type_pass=True), _video("A3", type_pass=None), _video("A4")]
    b = [_video("A1", type_pass=True), _video("A2", type_pass=True), _video("A3", type_pass=True),
         _video("A5", type_pass=True)]
    diff = xs.paired_difference(a, b, "type")
    assert (diff["n_pairs"], diff["excluded"], diff["mean_difference"]) == (2, 3, 0.5)
    assert diff == xs.paired_difference(a, b, "type")  # same seed, same interval


def _results_file(path: Path, version: str | None, videos: list[dict]) -> Path:
    payload = {"category": "Assault", "model_id": "m", "prompt_version": "incident-contract-v4",
               "inference_config": {}, "videos": videos}
    if version:
        payload["methodology"] = {**methodology.record(), "methodology_version": version}
    path.write_text(json.dumps(payload))
    return path


def test_aggregate_refuses_to_pool_methodology_versions(tmp_path):
    files = [_results_file(tmp_path / "assault__m.json", "evaluation-methodology-v1.0", [_video("A1")]),
             _results_file(tmp_path / "burglary__m.json", None, [_video("B1")])]
    with pytest.raises(eval_aggregate.MixedMethodologyError, match="different methodology versions"):
        eval_aggregate.summarize(files)


def test_aggregate_is_reproducible(tmp_path):
    videos = [_video(f"A{i}", type_pass=i % 3 != 0, severity=(3, 2 + i % 3)) for i in range(12)]
    files = [_results_file(tmp_path / "assault__m.json", "evaluation-methodology-v1.0", videos)]
    first, second = eval_aggregate.summarize(files), eval_aggregate.summarize(files)
    assert first == second
    assert first["methodology_version"] == "evaluation-methodology-v1.0"
    assert first["overall"]["field_intervals"]["type"]["ci95"] is not None
