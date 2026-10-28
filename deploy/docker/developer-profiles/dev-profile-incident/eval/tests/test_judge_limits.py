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

"""evaluation-methodology-v1.1: the judge's 1,500-token output limit, and truncated or invalid replies as failures."""

from __future__ import annotations

import sys
from pathlib import Path

import eval_gt
import methodology
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_run_lib  # noqa: E402


class Response:
    def __init__(self, content: str | None, *, finish_reason: str = "stop", reasoning: str | None = None,
                 status_code: int = 200):
        self.status_code = status_code
        self._body = {"choices": [{"message": {"content": content, "reasoning_content": reasoning},
                                   "finish_reason": finish_reason}], "usage": {"total_tokens": 1600}}

    def json(self):
        return self._body


@pytest.fixture
def judge(monkeypatch):
    """Serve the given replies in order and record every request body."""
    sent: list[dict] = []
    replies: list[Response] = []
    monkeypatch.setattr(eval_gt.config, "llm_base_url", lambda: "http://judge.invalid/v1")
    monkeypatch.setattr(eval_gt, "_sleep", lambda _s: None)

    def post(url, *, json, **_kwargs):
        sent.append(json)
        return replies.pop(0) if len(replies) > 1 else replies[0]

    monkeypatch.setattr(eval_gt.httpx, "post", post)
    return sent, replies


def test_every_judge_request_carries_the_output_limit(judge):
    sent, replies = judge
    replies.append(Response('{"score": 0.8}'))
    assert eval_gt.judge_description_similarity("a", "b").data == 0.8
    assert sent[0]["max_tokens"] == methodology.JUDGE_MAX_OUTPUT_TOKENS == 1500
    assert sent[0]["temperature"] == 0.0 and sent[0]["model"] == methodology.JUDGE_MODEL


def test_a_truncated_reply_is_a_failure_and_is_not_retried(judge):
    sent, replies = judge
    replies.append(Response('{"score": 0.9}', finish_reason="length"))  # a score, but cut off at the limit
    result = eval_gt.judge_description_similarity("a", "b")
    assert not result.ok and "truncated" in result.error and result.data is None
    assert len(sent) == 1


@pytest.mark.parametrize("content", ['{"score": 1.7}', '{"score": -0.2}', '{"score": "high"}', "Score: 7",
                                     "I cannot judge this.", "", None])
def test_an_invalid_reply_is_a_failure_never_a_clamped_score(judge, content):
    _, replies = judge
    replies.append(Response(content))
    result = eval_gt.judge_description_similarity("a", "b")
    assert not result.ok and result.data is None


def test_a_score_only_in_the_reasoning_is_not_a_score(judge):
    _, replies = judge
    replies.append(Response(None, reasoning='Thinking... {"score": 0.6}'))
    assert not eval_gt.judge_description_similarity("a", "b").ok


def test_a_valid_reply_after_an_invalid_one_is_used(judge):
    sent, replies = judge
    replies.extend([Response('{"score": 3}'), Response('{"score": 0.4}')])
    result = eval_gt.judge_description_similarity("a", "b")
    assert result.ok and result.data == 0.4 and len(sent) == 2


def test_a_truncated_description_score_is_unscored_and_stops_the_run(judge):
    _, replies = judge
    replies.append(Response('{"score": 0.9}', finish_reason="length"))
    field = eval_gt._judged_field_score("expected text", "predicted text")
    assert field["pass"] is None and field["score"] is None and "truncated" in field["error"]

    class Outcome:
        scoring_errors = [{"field": "description", "error": field["error"]}]
        fields = {"description": field}

    with pytest.raises(eval_run_lib.EvaluatorDependencyError):
        eval_run_lib.check_scoring_complete(Outcome())


def test_the_limit_is_recorded_in_every_result():
    assert methodology.record()["judge"]["request_settings"]["max_tokens"] == 1500
    # v1.2 changes only the item-matching threshold; the judge limit of v1.1 is kept.
    assert methodology.METHODOLOGY_VERSION == "evaluation-methodology-v1.2"
