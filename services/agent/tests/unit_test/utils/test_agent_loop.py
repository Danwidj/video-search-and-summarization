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

"""Unit tests for the agent loop's limits, step log and cap detection (no model, no network)."""

from __future__ import annotations

import asyncio

import openai
import pytest

from vss_agents.utils import agent_loop

pytestmark = pytest.mark.asyncio


async def _tool(name: str, *, fail: Exception | None = None, args: dict | None = None) -> str:
    async def impl() -> str:
        if fail is not None:
            raise fail
        return f"{name} done"

    return await agent_loop.run_guarded_tool(name, args or {}, impl)


def _agent(*calls: str, final: str = "the answer"):
    async def ask() -> str:
        for call in calls:
            await _tool(call)
        return final

    return ask


async def test_ok_run_logs_each_tool_in_order() -> None:
    result = await agent_loop.run_loop(_agent("a", "b"), "V1")
    assert result.status == "ok"
    assert result.answer == "the answer"
    assert [s["tool"] for s in result.steps] == ["a", "b"]
    assert all(s["ok"] and isinstance(s["ms"], int) for s in result.steps)


async def test_tool_sees_the_request_video() -> None:
    seen: list[str] = []

    async def ask() -> str:
        seen.append(agent_loop.current().video_id)
        return "x"

    await agent_loop.run_loop(ask, "V9")
    assert seen == ["V9"]


async def test_current_outside_a_run_fails_loudly() -> None:
    with pytest.raises(RuntimeError):
        agent_loop.current()


async def test_step_budget_stops_the_sixth_tool() -> None:
    ran: list[str] = []

    async def ask() -> str:
        for i in range(10):
            await agent_loop.run_guarded_tool(f"t{i}", {}, lambda i=i: _record(ran, i))
        return "never"

    result = await agent_loop.run_loop(ask, "V1", max_tool_steps=5)
    assert result.status == "aborted:step_budget"
    assert len(result.steps) == 5
    assert ran == ["0", "1", "2", "3", "4"]


async def _record(ran: list[str], i: int) -> str:
    ran.append(str(i))
    return "ok"


async def test_value_error_goes_back_to_the_model_and_the_run_continues() -> None:
    async def ask() -> str:
        with pytest.raises(ValueError):
            await _tool("bad", fail=ValueError("no such video"))
        await _tool("good")
        return "recovered"

    result = await agent_loop.run_loop(ask, "V1")
    assert result.status == "ok"
    assert [(s["tool"], s["ok"]) for s in result.steps] == [("bad", False), ("good", True)]
    assert result.steps[0]["error"] == "ValueError: no such video"


async def test_other_exception_aborts_the_run_after_one_step() -> None:
    async def ask() -> str:
        await _tool("db", fail=RuntimeError("database down"))
        await _tool("never")
        return "never"

    result = await agent_loop.run_loop(ask, "V1")
    assert result.status == "aborted:tool_failed:db"
    assert [s["tool"] for s in result.steps] == ["db"]


async def test_wall_clock_cancels_a_stalled_run() -> None:
    async def ask() -> str:
        await asyncio.sleep(30)
        return "never"

    result = await agent_loop.run_loop(ask, "V1", wall_seconds=0.05)
    assert result.status == "timeout"
    assert result.answer == ""


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (f"{agent_loop.CAP_ANSWER_PREFIX} 4 iterations. The agent repeatedly called tools.", "cap_reached"),
        ("It was a white van.", "ok"),
    ],
)
async def test_the_agents_cap_answer_is_not_reported_as_ok(answer: str, status: str) -> None:
    result = await agent_loop.run_loop(_agent("a", final=answer), "V1")
    assert result.status == status
    assert result.answer == answer


async def test_rate_limit_after_retries_is_busy() -> None:
    async def ask() -> str:
        raise openai.RateLimitError("slow down", response=_response(429), body=None)

    result = await agent_loop.run_loop(ask, "V1")
    assert result.status == "busy"


def _response(code: int):
    import httpx

    return httpx.Response(code, request=httpx.Request("POST", "http://model.test/v1/chat/completions"))


async def test_unexpected_failure_is_an_error_without_the_message() -> None:
    async def ask() -> str:
        raise KeyError("secret question text")

    result = await agent_loop.run_loop(ask, "V1")
    assert result.status == "error"


async def test_the_callers_own_cancellation_passes_through() -> None:
    async def ask() -> str:
        await asyncio.sleep(30)
        return "never"

    task = asyncio.ensure_future(agent_loop.run_loop(ask, "V1"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_actions_are_the_arguments_of_propose_tools_that_ran() -> None:
    async def ask() -> str:
        await agent_loop.run_guarded_tool("incident_read_report", {}, lambda: _record([], 0))
        await agent_loop.run_guarded_tool("propose_rename", {"key": "k1", "label": "van"}, lambda: _record([], 0))
        with pytest.raises(ValueError):
            await _tool("propose_rename", fail=ValueError("invented key"), args={"key": "zz"})
        return "done"

    result = await agent_loop.run_loop(ask, "V1")
    assert result.actions == [{"tool": "propose_rename", "args": {"key": "k1", "label": "van"}}]
