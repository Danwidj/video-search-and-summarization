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

"""Hard limits and a step log around a NAT ``tool_calling_agent`` run.

The agent itself is NAT's: declared under ``functions:`` in the config and resolved through the toolkit's
``SessionManager`` (the only path that writes Phoenix tool spans). It returns one final string and no steps, and it
has no wall clock, so this module adds what the route needs:

- a **step log**: every tool the agent ran, in order, written by :func:`run_guarded_tool` (a tool's own code calls it);
- a **step budget**: the call after ``max_tool_steps`` stops the run (``aborted:step_budget``);
- an **abort on failure**: a tool that raises anything but ``ValueError`` (a bad argument the model can fix) stops the
  run, because retrying a broken database or a stalled service only burns the budget (``aborted:tool_failed:<tool>``);
- a **wall clock** (``timeout``);
- **cap detection**: at ``max_iterations`` the agent returns a normal-looking string, so :func:`cap_reached` finds it
  and the run is reported as ``cap_reached``, never ``ok``. The agent also runs one tool more than ``max_iterations``;
- ``busy`` when the model endpoint still answers 429 after its retries.

A call whose arguments fail validation never reaches the tool, so it is not in the log. The per-model-call timeout and
retry count belong to the ``llms:`` entry the agent uses, not to this module.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import field
import logging
import time
from typing import TYPE_CHECKING
from typing import Any

import openai

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 5
WALL_CLOCK_SECONDS = 90.0
# What NAT's tool_calling_agent returns, as a normal answer, when it runs out of iterations.
CAP_ANSWER_PREFIX = "The tool calling agent could not produce a final answer within"
# A tool whose name starts like this only proposes a change; the route lists its arguments as ``actions``.
PROPOSAL_PREFIX = "propose_"
ERROR_TEXT_CHARS = 200


@dataclass
class LoopRun:
    """One request's video, limits and step log. Tools reach it through :func:`current`."""

    video_id: str
    max_tool_steps: int = MAX_TOOL_STEPS
    steps: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    task: asyncio.Future[Any] | None = None
    # The reviewer's unsaved draft, for the editor agent's proposal tools. The route sets it; the model never does.
    draft: Any = None
    # Questions already asked about the new evidence in this chat exchange, before this run. The route sets it.
    questions_asked: int = 0

    def stop(self, reason: str) -> None:
        """End the run: the first reason wins, and the agent's task is cancelled."""
        self.stop_reason = self.stop_reason or reason
        if self.task is not None:
            self.task.cancel()


@dataclass
class LoopResult:
    status: str
    answer: str
    steps: list[dict[str, Any]]
    wall_ms: int

    @property
    def actions(self) -> list[dict[str, Any]]:
        """The changes the agent proposed: the arguments of each ``propose_*`` tool that ran."""
        return [
            {"tool": step["tool"], "args": step["args"]}
            for step in self.steps
            if step["ok"] and str(step["tool"]).startswith(PROPOSAL_PREFIX)
        ]


_CURRENT: ContextVar[LoopRun | None] = ContextVar("agent_loop_run", default=None)


def current() -> LoopRun:
    """The run this tool call belongs to. A tool called outside :func:`run_loop` has none, so it fails loudly."""
    run = _CURRENT.get()
    if run is None:
        raise RuntimeError("this tool only runs inside an agent loop")
    return run


async def run_guarded_tool(name: str, args: dict[str, Any], impl: Callable[[], Awaitable[str]]) -> str:
    """Run one tool call under the step budget and write it to the step log.

    ``ValueError`` goes back to the model as the tool's error text, so it can fix its arguments. Any other
    exception stops the whole run and is raised again.
    """
    run = current()
    if len(run.steps) >= run.max_tool_steps:
        run.stop("step_budget")
        await asyncio.sleep(0)  # let the cancellation land before the tool does anything
    started = time.perf_counter()
    try:
        output = await impl()
    except Exception as exc:
        _log(run, name, args, started, ok=False, error=f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_CHARS])
        if not isinstance(exc, ValueError):
            run.stop(f"tool_failed:{name}")
            await asyncio.sleep(0)
        raise
    _log(run, name, args, started, ok=True)
    return output


def _log(run: LoopRun, name: str, args: dict[str, Any], started: float, *, ok: bool, error: str | None = None) -> None:
    step: dict[str, Any] = {"tool": name, "args": args, "ok": ok, "ms": round((time.perf_counter() - started) * 1000)}
    if error is not None:
        step["error"] = error
    run.steps.append(step)


def cap_reached(answer: str) -> bool:
    return answer.startswith(CAP_ANSWER_PREFIX)


async def run_loop(
    ask: Callable[[], Awaitable[str]],
    video_id: str,
    *,
    wall_seconds: float = WALL_CLOCK_SECONDS,
    max_tool_steps: int = MAX_TOOL_STEPS,
    draft: Any = None,
    questions_asked: int = 0,
) -> LoopResult:
    """Run ``ask`` (one call of the agent through its ``SessionManager``) under every limit and return how it ended.

    It never raises for a failed run: the outcome is ``LoopResult.status``, one of ``ok``, ``cap_reached``,
    ``timeout``, ``busy``, ``aborted:<reason>`` or ``error``. Only the caller's own cancellation passes through.
    """
    run = LoopRun(video_id=video_id, max_tool_steps=max_tool_steps, draft=draft, questions_asked=questions_asked)
    token = _CURRENT.set(run)
    started = time.perf_counter()
    status, answer = "ok", ""
    try:
        run.task = asyncio.ensure_future(ask())  # copies the context, so the tools see ``run``
        answer = str(await asyncio.wait_for(run.task, timeout=wall_seconds))
        if cap_reached(answer):
            status = "cap_reached"
    except TimeoutError:
        status = "timeout"
    except asyncio.CancelledError:
        if run.stop_reason is None:
            raise
        status = f"aborted:{run.stop_reason}"
    except openai.RateLimitError:
        status = "busy"
    except Exception as exc:
        # The type only: the message can hold the question or a link.
        logger.error("Agent loop failed: %s", type(exc).__name__)
        status = "error"
    finally:
        _CURRENT.reset(token)
    wall_ms = round((time.perf_counter() - started) * 1000)
    return LoopResult(status=status, answer=answer, steps=run.steps, wall_ms=wall_ms)
