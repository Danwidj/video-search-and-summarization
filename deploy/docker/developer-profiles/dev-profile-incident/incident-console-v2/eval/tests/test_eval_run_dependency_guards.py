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

"""Fail-fast guards: a dependency outage must abort the run, never continue
silently with a missing/default score treated as valid."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_run_lib import EvaluatorDependencyError, check_embedding_server_healthy, check_judge_ok  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text

    def json(self):
        return self._json


def test_check_embedding_server_healthy_passes_for_expected_model():
    with patch("httpx.get", return_value=_FakeResponse(200, {"status": "ok", "model": "sentence-transformers/all-MiniLM-L6-v2"})):
        check_embedding_server_healthy("http://127.0.0.1:8811/v1", expected_model="sentence-transformers/all-MiniLM-L6-v2")


def test_check_embedding_server_healthy_strips_v1_suffix_before_health():
    # Regression test: the server's /health route is at the root, not under
    # /v1 (only /v1/embeddings is under /v1) - appending "/health" to the
    # unstripped OpenAI-compatible base_url 404s every time, reproduced live
    # before this fix (hit /v1/health, which doesn't exist).
    with patch("httpx.get", return_value=_FakeResponse(200, {"status": "ok", "model": "m"})) as mock_get:
        check_embedding_server_healthy("http://127.0.0.1:8811/v1", expected_model="m")
    requested_url = mock_get.call_args[0][0]
    assert requested_url == "http://127.0.0.1:8811/health", requested_url


def test_check_embedding_server_healthy_handles_base_url_without_v1_suffix():
    with patch("httpx.get", return_value=_FakeResponse(200, {"status": "ok", "model": "m"})) as mock_get:
        check_embedding_server_healthy("http://127.0.0.1:8811", expected_model="m")
    assert mock_get.call_args[0][0] == "http://127.0.0.1:8811/health"


def test_check_embedding_server_healthy_raises_on_unreachable():
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(EvaluatorDependencyError, match="unreachable"):
            check_embedding_server_healthy("http://127.0.0.1:8811/v1", expected_model="sentence-transformers/all-MiniLM-L6-v2")


def test_check_embedding_server_healthy_raises_on_non_200():
    with patch("httpx.get", return_value=_FakeResponse(500, text="internal error")):
        with pytest.raises(EvaluatorDependencyError, match="HTTP 500"):
            check_embedding_server_healthy("http://127.0.0.1:8811/v1", expected_model="sentence-transformers/all-MiniLM-L6-v2")


def test_check_embedding_server_healthy_raises_on_wrong_model():
    with patch("httpx.get", return_value=_FakeResponse(200, {"status": "ok", "model": "some-other-model"})):
        with pytest.raises(EvaluatorDependencyError, match="expected the frozen"):
            check_embedding_server_healthy("http://127.0.0.1:8811/v1", expected_model="sentence-transformers/all-MiniLM-L6-v2")


@dataclass
class _FakeEvalResult:
    description_error: str = ""
    fields: dict = field(default_factory=dict)


def test_check_judge_ok_passes_when_no_error():
    check_judge_ok(_FakeEvalResult(description_error=""))


def test_check_judge_ok_raises_when_judge_failed():
    with pytest.raises(EvaluatorDependencyError, match="LLM judge call failed"):
        check_judge_ok(_FakeEvalResult(description_error="HTTP 401: unauthorized"))
