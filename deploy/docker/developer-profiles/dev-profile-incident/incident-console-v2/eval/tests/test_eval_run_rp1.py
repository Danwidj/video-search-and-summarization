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

"""``generate_rp1_report`` - reasoning_content must never be treated as a
valid report, empty/missing final content is always a failure, and retries
apply only when the call itself succeeded but returned no usable content."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_run  # noqa: E402


@dataclass
class _FakeChatResult:
    ok: bool
    content: str | None = None
    reasoning_content: str | None = None
    finish_reason: str | None = None
    raw: dict = field(default_factory=dict)
    error: str = ""
    status_code: int | None = None


def test_succeeds_first_attempt_with_real_content():
    with patch("eval_run.generate_report_with_rp1", return_value=_FakeChatResult(ok=True, content="INCIDENT REPORT\n...", finish_reason="stop")) as mock_call:
        report = eval_run.generate_rp1_report({"incident": {"type": "burglary"}})
    assert report["ok"] is True
    assert report["text"] == "INCIDENT REPORT\n..."
    assert report["attempts"] == 1
    assert mock_call.call_count == 1


def test_empty_content_with_reasoning_leak_is_never_used_as_text():
    leaked = "We need to produce a concise, objective incident report..." * 50
    with patch("eval_run.generate_report_with_rp1", return_value=_FakeChatResult(ok=True, content="", reasoning_content=leaked, finish_reason="length")):
        report = eval_run.generate_rp1_report({"incident": {}}, max_retries=0)
    assert report["ok"] is False
    assert report["text"] == ""
    assert leaked not in report["text"]
    assert "reasoning_content" in report["error"]


def test_retries_on_empty_content_then_succeeds():
    results = [
        _FakeChatResult(ok=True, content="", reasoning_content="scratchpad...", finish_reason="length"),
        _FakeChatResult(ok=True, content="INCIDENT REPORT\nreal report", finish_reason="stop"),
    ]
    with patch("eval_run.generate_report_with_rp1", side_effect=results) as mock_call:
        report = eval_run.generate_rp1_report({"incident": {}}, max_retries=2)
    assert report["ok"] is True
    assert report["text"] == "INCIDENT REPORT\nreal report"
    assert report["attempts"] == 2
    assert mock_call.call_count == 2


def test_exhausts_retries_when_content_never_arrives():
    with patch("eval_run.generate_report_with_rp1", return_value=_FakeChatResult(ok=True, content="", reasoning_content="scratchpad", finish_reason="length")) as mock_call:
        report = eval_run.generate_rp1_report({"incident": {}}, max_retries=2)
    assert report["ok"] is False
    assert report["text"] == ""
    assert report["attempts"] == 3  # first attempt + 2 retries
    assert mock_call.call_count == 3


def test_network_failure_is_never_retried():
    with patch("eval_run.generate_report_with_rp1", return_value=_FakeChatResult(ok=False, error="ConnectTimeout: ...")) as mock_call:
        report = eval_run.generate_rp1_report({"incident": {}}, max_retries=2)
    assert report["ok"] is False
    assert report["text"] == ""
    assert report["error"] == "ConnectTimeout: ..."
    assert report["attempts"] == 1
    assert mock_call.call_count == 1


def test_whitespace_only_content_is_treated_as_empty():
    with patch("eval_run.generate_report_with_rp1", return_value=_FakeChatResult(ok=True, content="   \n  ", finish_reason="stop")):
        report = eval_run.generate_rp1_report({"incident": {}}, max_retries=0)
    assert report["ok"] is False
    assert report["text"] == ""
