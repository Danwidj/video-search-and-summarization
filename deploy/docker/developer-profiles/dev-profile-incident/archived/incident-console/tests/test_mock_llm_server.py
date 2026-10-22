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

"""Mock LLM server: hashed-bow embeddings endpoint and the judge branch."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from eval_gt import _JUDGE_SYSTEM_PROMPT, _extract_score
from mock_llm_server import app

client = TestClient(app)


def _cosine(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_embeddings_returns_one_vector_per_input():
    resp = client.post("/v1/embeddings", json={"model": "embedding", "input": ["hello world", "goodbye"]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert all(len(item["embedding"]) == 64 for item in body["data"])


def test_embeddings_near_duplicate_scores_higher_than_unrelated():
    resp = client.post(
        "/v1/embeddings",
        json={
            "model": "embedding",
            "input": [
                "a person forces open a side door and takes a cash box",
                "an individual pries open a door and removes a cash box",
                "a dog runs across an empty parking lot at night",
            ],
        },
    )
    vectors = [item["embedding"] for item in resp.json()["data"]]
    near = _cosine(vectors[0], vectors[1])
    far = _cosine(vectors[0], vectors[2])
    assert near > far


def test_chat_completions_judge_branch_returns_score_in_unit_interval():
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "incident-judge",
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "EXPECTED: a cat sleeps on a windowsill\nPREDICTED: a cat naps on a windowsill",
                },
            ],
        },
    )
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    score = _extract_score(content)
    assert score is not None
    assert 0.0 <= score <= 1.0


def test_chat_completions_judge_branch_is_monotonic_on_near_vs_far_pair():
    def score_for(expected, predicted):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "incident-judge",
                "messages": [
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"EXPECTED: {expected}\nPREDICTED: {predicted}"},
                ],
            },
        )
        return _extract_score(resp.json()["choices"][0]["message"]["content"])

    near_score = score_for(
        "a person forces open a side door and takes a cash box",
        "an individual pries open a door and removes a cash box",
    )
    far_score = score_for(
        "a person forces open a side door and takes a cash box",
        "a dog runs across an empty parking lot at night",
    )
    assert near_score > far_score


def test_chat_completions_non_judge_request_falls_through_to_canned_report():
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-incident-llm",
            "messages": [{"role": "user", "content": "two vehicles collide at the junction"}],
        },
    )
    body = resp.json()["choices"][0]["message"]["content"]
    assert "incident_type" in body
