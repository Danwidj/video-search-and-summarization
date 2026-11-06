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

"""Tests for stopping an analysis when its caller disconnects (the console's 300 s abort)."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from vss_agents.utils import run_cancel
from vss_agents.utils.crop_evidence import DefaultDetector
from vss_agents.utils.crop_evidence import DetectorBreaker
from vss_agents.utils.crop_evidence import FakeDetector
from vss_agents.utils.crop_evidence import GuardedDetector


class TestRunUntilDisconnect:
    @pytest.mark.asyncio
    async def test_a_run_that_finishes_returns_its_result_and_never_asks_about_the_caller_twice_for_a_fast_run(
        self,
    ) -> None:
        async def work() -> str:
            return "report"

        async def connected() -> bool:
            return False

        assert await run_cancel.run_until_disconnect(work, connected, poll_seconds=0.01) == "report"

    @pytest.mark.asyncio
    async def test_an_error_of_the_run_is_raised_unchanged(self) -> None:
        async def work() -> str:
            raise ValueError("boom")

        async def connected() -> bool:
            return False

        with pytest.raises(ValueError, match="boom"):
            await run_cancel.run_until_disconnect(work, connected, poll_seconds=0.01)

    @pytest.mark.asyncio
    async def test_a_disconnect_stops_the_run_and_lets_its_cleanup_finish(self) -> None:
        events: list[str] = []

        async def slow_upstream() -> str:
            try:
                await asyncio.sleep(30)  # a simulated slow hosted model
                events.append("report written")
                return "report"
            finally:
                events.append("cleanup")  # the scratch-prefix delete

        async def gone() -> bool:
            return True

        started = time.monotonic()
        with pytest.raises(run_cancel.AnalysisCancelledError):
            await run_cancel.run_until_disconnect(slow_upstream, gone, poll_seconds=0.01)
        assert events == ["cleanup"] and time.monotonic() - started < 5

    @pytest.mark.asyncio
    async def test_a_disconnect_sets_the_flag_a_worker_thread_checks_before_each_hosted_call(self) -> None:
        calls: list[str] = []
        seen: list[str] = []

        def worker() -> None:
            for attempt in range(100):
                try:
                    run_cancel.raise_if_cancelled()
                except run_cancel.AnalysisCancelledError:
                    seen.append("stopped")
                    return
                calls.append(f"call {attempt}")
                time.sleep(0.01)

        async def work() -> None:
            await asyncio.to_thread(worker)

        polls = 0

        async def gone_after_a_moment() -> bool:
            nonlocal polls
            polls += 1
            return polls >= 3

        with pytest.raises(run_cancel.AnalysisCancelledError):
            await run_cancel.run_until_disconnect(work, gone_after_a_moment, poll_seconds=0.02)
        await asyncio.sleep(0.2)  # the thread outlives the task but makes no further call
        count = len(calls)
        await asyncio.sleep(0.1)
        assert seen == ["stopped"] and len(calls) == count < 100

    def test_the_flag_is_off_outside_a_run(self) -> None:
        run_cancel.raise_if_cancelled()
        started = time.monotonic()
        run_cancel.sleep(0.01)
        assert time.monotonic() - started < 1

    @pytest.mark.asyncio
    async def test_a_wait_between_retries_ends_at_once_on_an_abort(self) -> None:
        outcome: list[str] = []

        def worker() -> None:
            started = time.monotonic()
            try:
                run_cancel.sleep(20)  # a retry-after wait
            except run_cancel.AnalysisCancelledError:
                outcome.append("woken" if time.monotonic() - started < 5 else "slept")

        async def work() -> None:
            await asyncio.to_thread(worker)

        polls = 0

        async def gone() -> bool:
            nonlocal polls
            polls += 1
            return polls >= 2

        with pytest.raises(run_cancel.AnalysisCancelledError):
            await run_cancel.run_until_disconnect(work, gone, poll_seconds=0.02)
        await asyncio.sleep(0.3)
        assert outcome == ["woken"]


class TestHostedCallsStopAfterAnAbort:
    @staticmethod
    def _cancelled() -> threading.Event:
        event = threading.Event()
        event.set()
        return event

    def test_a_guarded_detector_makes_no_call(self) -> None:
        detector = FakeDetector(detections=[])
        guarded = GuardedDetector(detector, DetectorBreaker("test"))
        token = run_cancel._CANCEL.set(self._cancelled())
        try:
            with pytest.raises(run_cancel.AnalysisCancelledError):
                guarded.detect(MagicMock(), "x")
        finally:
            run_cancel._CANCEL.reset(token)

    def test_grounding_and_zoom_requests_send_nothing(self) -> None:
        detector = DefaultDetector(api_key="k")
        token = run_cancel._CANCEL.set(self._cancelled())
        try:
            with patch("vss_agents.utils.crop_evidence.httpx.post") as post:
                with pytest.raises(run_cancel.AnalysisCancelledError):
                    detector._request_box({})
                with pytest.raises(run_cancel.AnalysisCancelledError):
                    detector._chat_json([b"jpeg"], "look", dict)
            post.assert_not_called()
        finally:
            run_cancel._CANCEL.reset(token)

    def test_a_retry_after_an_abort_is_not_sent(self) -> None:
        detector = DefaultDetector(api_key="k")
        event = threading.Event()
        limited = MagicMock(status_code=429, headers={"retry-after": "20"})
        limited.raise_for_status.side_effect = httpx.HTTPStatusError("429", request=MagicMock(), response=limited)

        def abort_during_the_first_call(*_: object, **__: object) -> MagicMock:
            event.set()  # the console aborts while the first call is in flight
            return limited

        token = run_cancel._CANCEL.set(event)
        try:
            with patch("vss_agents.utils.crop_evidence.httpx.post", side_effect=abort_during_the_first_call) as post:
                started = time.monotonic()
                with pytest.raises(run_cancel.AnalysisCancelledError):
                    detector._chat_json([b"jpeg"], "look", dict)
            assert post.call_count == 1 and time.monotonic() - started < 5
        finally:
            run_cancel._CANCEL.reset(token)
