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
        sent.update(url=url, body=json, timeout=timeout)
        return _FakeResponse(200, {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    monkeypatch.setattr(eval_vlm_client.requests, "post", fake_post)
    return sent


def test_p1_sends_video_url_first_then_contract_prompt_with_strict_schema(monkeypatch):
    sent = _capture(monkeypatch)
    eval_vlm_client.analyze_video_with_p1("m", "https://r2.example/v.mp4?sig")
    assert sent["timeout"] == 300.0
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
    assert sent["timeout"] == 300.0
    body = sent["body"]
    text = body["messages"][0]["content"]
    assert text.startswith(contract.report_prompt_template().split("{structured_incident_json}")[0])
    assert '"type": "burglary"' in text
    assert "media_io_kwargs" not in body and "response_format" not in body


def test_default_timeout_matches_inference_json():
    assert eval_vlm_client.DEFAULT_TIMEOUT == 300.0
    assert eval_vlm_client.DEFAULT_TIMEOUT == float(contract.load_inference()["models"][0]["timeout_seconds"])

# --- P1 processing time -----------------------------------------------------------------


def _clock(monkeypatch, start=100.0, end=112.5):
    ticks = iter([start, end])
    monkeypatch.setattr(eval_vlm_client.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))


def test_elapsed_time_is_the_request_round_trip(monkeypatch):
    _clock(monkeypatch)
    body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(eval_vlm_client.requests, "post", lambda *a, **k: _FakeResponse(200, body))
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.ok and result.elapsed_s == pytest.approx(12.5)
    assert result.started_at and result.finished_at and result.started_at <= result.finished_at


def test_elapsed_time_is_recorded_for_an_http_error(monkeypatch):
    _clock(monkeypatch)
    monkeypatch.setattr(eval_vlm_client.requests, "post", lambda *a, **k: _FakeResponse(503, {"error": "busy"}))
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.ok is False and result.status_code == 503 and result.elapsed_s == pytest.approx(12.5)


def test_elapsed_time_is_recorded_for_a_timeout(monkeypatch):
    _clock(monkeypatch, end=400.0)

    def timeout(*a, **k):
        raise eval_vlm_client.requests.ReadTimeout("read timed out")

    monkeypatch.setattr(eval_vlm_client.requests, "post", timeout)
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.ok is False and result.error.startswith("ReadTimeout") and result.elapsed_s == pytest.approx(300.0)


def test_no_request_means_no_elapsed_time(monkeypatch):
    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", ""))
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.ok is False and result.elapsed_s is None


def test_p1_uses_the_contract_timeout(monkeypatch):
    sent = {}

    def fake_post(url, *, headers, json, timeout):
        sent["timeout"] = timeout
        return _FakeResponse(200, {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    monkeypatch.setattr(eval_vlm_client.requests, "post", fake_post)
    eval_vlm_client.analyze_video_with_p1("m", "https://r2.example/v.mp4?sig")
    assert sent["timeout"] == eval_vlm_client.DEFAULT_TIMEOUT == 300.0


# --- P1 rate-limit policy: pacing, HTTP 429 retries only ------------------------------------

from eval_vlm_client import P1_RATE_LIMIT_POLICY, ChatResult, P1Pacer, analyze_video_with_p1_rate_limited  # noqa: E402


class _Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _sequence(monkeypatch, results, clock, call_s=5.0):
    calls = iter(results)

    def fake_p1(model, url):
        clock.now += call_s
        return next(calls)

    monkeypatch.setattr(eval_vlm_client, "analyze_video_with_p1", fake_p1)


def _ok(elapsed=12.0):
    return ChatResult(ok=True, content="{}", finish_reason="stop", status_code=200, elapsed_s=elapsed)


def _limited(retry_after=None, elapsed=7.0):
    return ChatResult(ok=False, status_code=429, error="RateLimitError", failure_kind="rate_limited",
                      retry_after_s=retry_after, elapsed_s=elapsed)


def test_policy_is_fixed():
    assert P1_RATE_LIMIT_POLICY == {"inter_call_delay_s": 20.0, "cooldown_s": 60.0, "max_rate_limit_retries": 2,
                                    "honor_retry_after": True}


def test_429_is_retried_after_the_cooldown_and_time_is_the_successful_attempt_only(monkeypatch):
    clock = _Clock()
    _sequence(monkeypatch, [_limited(), _ok(elapsed=12.0)], clock)
    outcome = analyze_video_with_p1_rate_limited("m", "u", pacer=P1Pacer(sleep=clock.sleep, monotonic=clock.monotonic))
    assert outcome.result.ok and outcome.result.elapsed_s == 12.0
    assert outcome.rate_limit_retries == 1 and clock.sleeps == [60.0]
    summary = outcome.summary()
    assert summary["attempt_count"] == 2 and summary["final_attempt_ok"] is True
    assert [a["wait_before_s"] for a in summary["attempts"]] == [0.0, 60.0]
    assert [a["wait_reason"] for a in summary["attempts"]] == [None, "rate_limit_cooldown"]
    assert summary["rate_limit_rejections"] == ["RateLimitError"] and summary["total_wait_s"] == 60.0


def test_429_gives_up_after_two_retries(monkeypatch):
    clock = _Clock()
    _sequence(monkeypatch, [_limited(), _limited(), _limited()], clock)
    outcome = analyze_video_with_p1_rate_limited("m", "u", pacer=P1Pacer(sleep=clock.sleep, monotonic=clock.monotonic))
    assert not outcome.result.ok and outcome.result.failure_kind == "rate_limited"
    assert len(outcome.attempts) == 3 and clock.sleeps == [60.0, 60.0]
    assert outcome.summary()["final_attempt_ok"] is False


@pytest.mark.parametrize(("retry_after", "expected_wait"), [(90.0, 90.0), (10.0, 60.0), (None, 60.0)])
def test_retry_after_is_honoured_only_when_longer(monkeypatch, retry_after, expected_wait):
    clock = _Clock()
    _sequence(monkeypatch, [_limited(retry_after=retry_after), _ok()], clock)
    analyze_video_with_p1_rate_limited("m", "u", pacer=P1Pacer(sleep=clock.sleep, monotonic=clock.monotonic))
    assert clock.sleeps == [expected_wait]


@pytest.mark.parametrize("final", [
    ChatResult(ok=False, status_code=500, error="HTTP 500", failure_kind="http_error"),
    ChatResult(ok=False, error="ReadTimeout: x", failure_kind="timeout", elapsed_s=300.0),
    ChatResult(ok=False, status_code=200, error="no completion", failure_kind="invalid_response"),
    ChatResult(ok=True, content="not json at all", finish_reason="stop", status_code=200),  # parse/contract: model output
])
def test_nothing_but_429_is_retried(monkeypatch, final):
    clock = _Clock()
    _sequence(monkeypatch, [final], clock)
    outcome = analyze_video_with_p1_rate_limited("m", "u", pacer=P1Pacer(sleep=clock.sleep, monotonic=clock.monotonic))
    assert len(outcome.attempts) == 1 and clock.sleeps == [] and outcome.result is final


def test_pacing_waits_the_remainder_of_the_inter_call_delay(monkeypatch):
    clock = _Clock()
    pacer = P1Pacer(sleep=clock.sleep, monotonic=clock.monotonic)
    _sequence(monkeypatch, [_ok(), _ok(), _ok()], clock)
    first = analyze_video_with_p1_rate_limited("a", "u", pacer=pacer)
    clock.now += 5.0  # e.g. validation and judging between calls
    second = analyze_video_with_p1_rate_limited("b", "u", pacer=pacer)
    clock.now += 30.0
    third = analyze_video_with_p1_rate_limited("c", "u", pacer=pacer)
    assert first.attempts[0]["wait_before_s"] == 0.0
    assert second.attempts[0]["wait_before_s"] == 15.0 and second.attempts[0]["wait_reason"] == "pacing"
    assert third.attempts[0]["wait_before_s"] == 0.0
    assert clock.sleeps == [15.0]


class _HeaderResponse(_FakeResponse):
    def __init__(self, status_code, body, headers):
        super().__init__(status_code, body)
        self.headers = headers


@pytest.mark.parametrize(("status", "headers", "kind", "retry_after"), [
    (429, {"Retry-After": "45"}, "rate_limited", 45.0),
    (429, {}, "rate_limited", None),
    (503, {"Retry-After": "45"}, "http_error", None),
])
def test_chat_completion_classifies_failures(monkeypatch, status, headers, kind, retry_after):
    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    monkeypatch.setattr(eval_vlm_client.requests, "post", lambda *a, **k: _HeaderResponse(status, {"e": 1}, headers))
    result = chat_completion("m", [{"role": "user", "content": "hi"}])
    assert result.failure_kind == kind and result.retry_after_s == retry_after


def test_chat_completion_marks_timeouts_and_transport_errors(monkeypatch):
    monkeypatch.setattr(eval_vlm_client, "gateway_credentials", lambda: ("https://gw.example/v1", "key"))
    for exc, kind in ((eval_vlm_client.requests.ReadTimeout("t"), "timeout"),
                      (eval_vlm_client.requests.ConnectionError("c"), "transport_error")):
        def boom(*a, _exc=exc, **k):
            raise _exc
        monkeypatch.setattr(eval_vlm_client.requests, "post", boom)
        assert chat_completion("m", [{"role": "user", "content": "hi"}]).failure_kind == kind


def test_retry_after_http_date():
    from email.utils import format_datetime
    from datetime import datetime, timedelta, timezone

    when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    assert 110 <= eval_vlm_client._retry_after_seconds({"Retry-After": when}) <= 120
    assert eval_vlm_client._retry_after_seconds({"Retry-After": "soon"}) is None
