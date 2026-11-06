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

"""Wait-and-retry on HTTP 429 and the streamed reply of the main analysis call (``run_p1`` and its retry wrapper)."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import pytest

from vss_agents.incident_contract import IncidentExtractionError
from vss_agents.tools import incident_report_gen as gen
from vss_agents.tools.incident_report_gen import IncidentReportGenConfig
from vss_agents.tools.incident_report_gen import P1RateLimitedError
from vss_agents.tools.incident_report_gen import P1StreamError
from vss_agents.tools.incident_report_gen import parse_retry_after
from vss_agents.tools.incident_report_gen import run_p1
from vss_agents.tools.incident_report_gen import run_p1_with_retry

from .test_incident_report_gen import MODEL_OUTPUT
from .test_incident_report_gen import VIDEO_URL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

CONTENT = json.dumps(MODEL_OUTPUT)
SSE = {"content-type": "text/event-stream; charset=utf-8"}


def _config() -> IncidentReportGenConfig:
    return IncidentReportGenConfig(
        vlm_base_url="https://switchyard.example",
        vlm_model_name="nvidia/cosmos-3-nano-reasoner",
        rp1_base_url="https://switchyard.example/",
    )


def _event(delta: dict | None = None, finish: str | None = None, usage: dict | None = None) -> str:
    chunk: dict = {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk)}\n\n"


def _stream_text(content: str, finish: str = "stop", size: int = 40) -> str:
    pieces = [content[i : i + size] for i in range(0, len(content), size)] or [""]
    events = [_event({"role": "assistant", "content": ""})]
    events += [_event({"content": piece}) for piece in pieces]
    events += [_event(finish=finish), _event(usage={"prompt_tokens": 7, "completion_tokens": 3}), "data: [DONE]\n\n"]
    return "".join(events)


def _streamed(content: str, finish: str = "stop") -> httpx.Response:
    return httpx.Response(200, headers=SSE, content=_stream_text(content, finish).encode())


class _DroppingStream(httpx.AsyncByteStream):
    """Sends the first events of a reply, then the connection dies."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.text.encode()
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def waits():
    """Records every wait instead of sleeping."""
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    with patch.object(gen, "_sleep", fake_sleep):
        yield recorded


class TestRetryAfter:
    @pytest.mark.parametrize(
        ("value", "seconds"),
        [("7", 7.0), (" 2.5 ", 2.5), ("0", 0.0), ("-3", 0.0), (None, None), ("", None), ("soon", None), ("nan", None)],
    )
    def test_the_header_is_read_as_seconds(self, value, seconds):
        assert parse_retry_after(value) == seconds

    def test_an_http_date_is_the_wait_until_then(self):
        date = "Wed, 21 Oct 2099 07:28:00 GMT"
        assert parse_retry_after(date) > 60 * 60 * 24 * 365
        assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


class TestStreamedReply:
    @pytest.mark.asyncio
    async def test_the_request_asks_for_a_stream_and_keeps_the_rest(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return _streamed(CONTENT)

        async with _client(handler) as client:
            await run_p1(client, _config(), VIDEO_URL)
        expected = gen.p1_request_body("nvidia/cosmos-3-nano-reasoner", VIDEO_URL)
        assert seen[0]["stream"] is True and expected["stream"] is False
        assert seen[0]["stream_options"] == {"include_usage": True}
        assert {k: v for k, v in seen[0].items() if k not in ("stream", "stream_options")} == {
            k: v for k, v in expected.items() if k != "stream"
        }

    @pytest.mark.asyncio
    async def test_a_streamed_reply_assembles_the_same_text_as_a_plain_one(self):
        async with _client(lambda _r: _streamed(CONTENT)) as client:
            streamed = await run_p1(client, _config(), VIDEO_URL)
        plain_reply = httpx.Response(
            200, json={"choices": [{"message": {"content": CONTENT}, "finish_reason": "stop"}]}
        )
        async with _client(lambda _r: plain_reply) as client:
            plain = await run_p1(client, _config(), VIDEO_URL)
        assert streamed == plain
        assert streamed[1] == CONTENT and streamed[2] == "stop"

    @pytest.mark.asyncio
    async def test_a_length_stop_is_still_recognised(self):
        async with _client(lambda _r: _streamed("", "length")) as client:
            with pytest.raises(IncidentExtractionError, match="finish_reason=length") as excinfo:
                await run_p1(client, _config(), VIDEO_URL)
        assert excinfo.value.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_a_runaway_streamed_reply_is_retried_once_as_before(self):
        replies = [_streamed("x" * (gen.MAX_P1_OUTPUT_CHARS + 1), "length"), _streamed(CONTENT)]
        async with _client(lambda _r: replies.pop(0)) as client:
            report, _raw, _finish, attempts = await run_p1_with_retry(client, _config(), VIDEO_URL)
        assert report["incident"]["type"] == "burglary" and len(attempts) == 2 and not replies

    @pytest.mark.asyncio
    async def test_a_stream_that_drops_midway_is_a_failed_attempt(self):
        partial = _event({"content": CONTENT[:30]})
        response = httpx.Response(200, headers=SSE, stream=_DroppingStream(partial))
        async with _client(lambda _r: response) as client:
            with pytest.raises(P1StreamError, match="dropped after 30 characters"):
                await run_p1(client, _config(), VIDEO_URL)

    @pytest.mark.asyncio
    async def test_a_stream_that_ends_without_a_finish_reason_is_a_failed_attempt(self):
        text = _event({"content": CONTENT[:30]})
        async with _client(lambda _r: httpx.Response(200, headers=SSE, content=text.encode())) as client:
            with pytest.raises(P1StreamError, match="no finish reason"):
                await run_p1(client, _config(), VIDEO_URL)

    @pytest.mark.asyncio
    async def test_an_error_event_in_the_stream_is_a_failed_attempt(self):
        text = _event({"content": "{"}) + 'data: {"error": {"message": "engine overloaded"}}\n\n'
        async with _client(lambda _r: httpx.Response(200, headers=SSE, content=text.encode())) as client:
            with pytest.raises(P1StreamError, match="engine overloaded"):
                await run_p1(client, _config(), VIDEO_URL)

    @pytest.mark.asyncio
    async def test_the_usage_of_a_streamed_reply_reaches_the_telemetry(self):
        telemetry: dict = {}
        async with _client(lambda _r: _streamed(CONTENT)) as client:
            await run_p1(client, _config(), VIDEO_URL, telemetry=telemetry)
        assert telemetry["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}


class TestWaitAndRetryOn429:
    @staticmethod
    def _sequence(*replies: httpx.Response):
        queue = list(replies)
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return queue.pop(0) if len(queue) > 1 else queue[0]

        return handler, calls

    @pytest.mark.asyncio
    async def test_a_429_with_retry_after_waits_that_long_then_succeeds(self, waits):
        limited = httpx.Response(429, headers={"retry-after": "7"}, text="Priority-based rate limit exceeded")
        handler, calls = self._sequence(limited, _streamed(CONTENT))
        async with _client(handler) as client:
            _report, raw, finish, attempts = await run_p1_with_retry(
                client, _config(), VIDEO_URL, deadline=time.monotonic() + 240
            )
        assert waits == [7.0] and len(calls) == 2 and raw == CONTENT and finish == "stop" and len(attempts) == 1

    @pytest.mark.asyncio
    async def test_a_429_without_the_header_backs_off_with_jitter(self, waits):
        handler, calls = self._sequence(httpx.Response(429), httpx.Response(429), _streamed(CONTENT))
        async with _client(handler) as client:
            await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=time.monotonic() + 240)
        assert len(calls) == 3 and len(waits) == 2
        assert 2.5 <= waits[0] <= 5.0 and 5.0 <= waits[1] <= 10.0  # doubling, jittered between half and full

    @pytest.mark.asyncio
    async def test_repeated_429s_stop_at_the_attempt_limit(self, waits):
        handler, calls = self._sequence(httpx.Response(429, headers={"retry-after": "1"}))
        async with _client(handler) as client:
            with pytest.raises(P1RateLimitedError, match="HTTP 429"):
                await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=time.monotonic() + 240)
        assert len(calls) == gen.P1_MAX_RATE_LIMIT_CALLS and len(waits) == gen.P1_MAX_RATE_LIMIT_CALLS - 1

    @pytest.mark.asyncio
    async def test_a_wait_that_does_not_fit_the_budget_is_not_taken(self, waits):
        handler, calls = self._sequence(httpx.Response(429, headers={"retry-after": "100"}))
        async with _client(handler) as client:
            with pytest.raises(P1RateLimitedError):
                await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=time.monotonic() + 120)
        assert waits == [] and len(calls) == 1  # 100 s plus a 60 s call does not fit in 120 s

    @pytest.mark.asyncio
    async def test_the_waits_together_never_pass_the_budget(self, waits):
        deadline = time.monotonic() + 240
        handler, calls = self._sequence(httpx.Response(429, headers={"retry-after": "60"}))

        async def spend(seconds: float) -> None:  # the fake clock: each wait really uses that much of the budget
            waits.append(seconds)
            nonlocal deadline
            deadline -= seconds

        with patch.object(gen, "_sleep", spend):
            async with _client(handler) as client:
                with pytest.raises(P1RateLimitedError):
                    await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=deadline)
        assert sum(waits) <= 240 - gen.P1_RATE_LIMIT_MIN_CALL_SECONDS and len(calls) == len(waits) + 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500, 524])
    async def test_other_errors_are_not_retried(self, waits, status):
        handler, calls = self._sequence(httpx.Response(status, text="no"))
        async with _client(handler) as client:
            with pytest.raises(RuntimeError, match=f"HTTP {status}"):
                await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=time.monotonic() + 240)
        assert waits == [] and len(calls) == 1

    @pytest.mark.asyncio
    async def test_a_dropped_stream_is_not_retried_as_a_429(self, waits):
        response = httpx.Response(200, headers=SSE, stream=_DroppingStream(_event({"content": "{"})))
        handler, calls = self._sequence(response)
        async with _client(handler) as client:
            with pytest.raises(P1StreamError):
                await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=time.monotonic() + 240)
        assert waits == [] and len(calls) == 1

    @pytest.mark.asyncio
    async def test_each_429_and_the_streamed_usage_reach_the_run_provenance(self, waits):
        from vss_agents.utils import run_provenance

        handler, _ = self._sequence(httpx.Response(429, headers={"retry-after": "1"}), _streamed(CONTENT))
        with run_provenance.collecting() as provenance:
            async with _client(handler) as client:
                await run_p1_with_retry(client, _config(), VIDEO_URL, deadline=time.monotonic() + 240)
        p1 = provenance.to_dict(contract_version="v", flags={})["stages"]["p1"]
        assert p1["calls"] == 2 and p1["failed"] == 1 and waits == [1.0]
        assert p1["prompt_tokens"] == 7 and p1["completion_tokens"] == 3
