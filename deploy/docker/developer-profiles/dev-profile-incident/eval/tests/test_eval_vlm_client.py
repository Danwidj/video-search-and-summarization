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

"""The eval VLM client: fail-soft transport and the contract P1/RP1 request shape - no live network calls."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_vlm_client  # noqa: E402
import pytest  # noqa: E402
import contract  # noqa: E402
from eval_vlm_client import FIXED_INFERENCE_CONFIG, chat_completion  # noqa: E402







def test_fixed_inference_config_is_the_only_variable_across_models():
    # A guard against accidental per-model drift: this dict must never be
    # mutated per model/category/video by any caller - it's read, not built.
    assert FIXED_INFERENCE_CONFIG == {"temperature": 0.0, "max_tokens": 4096}


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


@pytest.mark.parametrize(
    ("status", "body"),
    [(200, None), (200, []), (200, {}), (200, {"choices": []}), (400, None), (500, "oops")],
)
def test_chat_completion_non_completion_body_fails_soft(monkeypatch, status, body):
    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    monkeypatch.setattr(eval_vlm_client.requests, "post", lambda *a, **k: _FakeResponse(status, body))
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.ok is False
    assert result.status_code == status
    assert result.error


def test_chat_completion_success(monkeypatch):
    body = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    monkeypatch.setattr(eval_vlm_client.requests, "post", lambda *a, **k: _FakeResponse(200, body))
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.ok and result.content == "hello" and result.finish_reason == "stop"


def _capture(monkeypatch):
    sent = {}

    def fake_post(url, *, headers, json, timeout):
        sent.update(url=url, body=json)
        return _FakeResponse(200, {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    monkeypatch.setattr(eval_vlm_client.requests, "post", fake_post)
    return sent


def test_p1_sends_video_url_first_then_contract_prompt_with_strict_schema(monkeypatch):
    sent = _capture(monkeypatch)
    eval_vlm_client.analyze_video_with_p1("m", "https://r2.example/v.mp4?sig")
    body = sent["body"]
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "video_url", "video_url": {"url": "https://r2.example/v.mp4?sig"}}
    assert parts[1] == {"type": "text", "text": contract.extraction_prompt()}
    assert body["response_format"] == contract.response_format()
    assert body["max_tokens"] == 16384
    assert body["media_io_kwargs"] == {"video": {"num_frames": 64}}
    assert body["temperature"] == 0.0
    assert "data:video" not in str(body)  # never base64


def test_rp1_uses_contract_report_prompt_and_no_video_settings(monkeypatch):
    sent = _capture(monkeypatch)
    eval_vlm_client.generate_report_with_rp1("rp1-model", {"incident": {"type": "burglary"}})
    body = sent["body"]
    text = body["messages"][0]["content"]
    assert text.startswith(contract.report_prompt_template().split("{structured_incident_json}")[0])
    assert '"type": "burglary"' in text
    assert "media_io_kwargs" not in body and "response_format" not in body

