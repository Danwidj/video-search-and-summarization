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

"""Stopping an analysis when its caller gives up.

The console aborts ``POST /analyze`` after 600 s. Without this module the agent kept working for another minute or
more: it made hosted model calls nobody would read and then wrote a report revision the console had already marked
failed. :func:`run_until_disconnect` runs the analysis as a task and, when the client has gone, cancels it and sets
the run's cancel flag (a :class:`threading.Event` in a context variable, so it reaches the ``asyncio.to_thread``
workers that make the crop, tracking and zoom calls). Every hosted call checks the flag first
(:func:`raise_if_cancelled`) and the waits between retries end at once (:func:`sleep`), so after an abort the run
makes no new hosted call and writes no report. A call already sent cannot be recalled: it finishes and its answer is
dropped.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import threading
import time
from typing import TYPE_CHECKING
from typing import TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable

    from starlette.requests import Request

_CANCEL: ContextVar[threading.Event | None] = ContextVar("incident_run_cancel", default=None)
_T = TypeVar("_T")

DISCONNECT_POLL_SECONDS = 1.0


async def run_until_request_disconnect(  # noqa: UP047 - the project's mypy target predates PEP 695
    start: Callable[[], Awaitable[_T]], request: Request
) -> _T:
    """:func:`run_until_disconnect` for a request, whatever middleware sits in front of the route.

    ``request.is_disconnected()`` cannot be polled here: it cancels its own ``receive()`` before it can yield, which
    only works when ``receive`` answers at once (raw uvicorn). Behind a ``BaseHTTPMiddleware`` (NAT installs one on
    every app) the wrapped ``receive`` waits on the real one, so the poll always said "connected" and a run whose
    caller had gone still saved a report (job 59, 6 Nov 2026). A watcher task that awaits ``receive()`` until
    ``http.disconnect`` arrives works in both cases. The route's body has been read by now, so the only message
    left is the disconnect.
    """

    async def wait_for_disconnect() -> None:
        while (await request.receive())["type"] != "http.disconnect":
            pass

    watcher = asyncio.ensure_future(wait_for_disconnect())

    async def is_disconnected() -> bool:
        return watcher.done()

    try:
        return await run_until_disconnect(start, is_disconnected)
    finally:
        watcher.cancel()


class AnalysisCancelledError(RuntimeError):
    """The caller of the analysis disconnected, so the run stopped."""


def raise_if_cancelled() -> None:
    """Raise :class:`AnalysisCancelledError` when the current run's caller has gone; a no-op outside a run."""
    event = _CANCEL.get()
    if event is not None and event.is_set():
        raise AnalysisCancelledError("the caller of the analysis disconnected")


def sleep(seconds: float) -> None:
    """``time.sleep`` for a worker thread that ends at once, with :class:`AnalysisCancelledError`, on an abort."""
    event = _CANCEL.get()
    if event is None:
        time.sleep(seconds)
    elif event.wait(seconds):
        raise AnalysisCancelledError("the caller of the analysis disconnected")


async def run_until_disconnect(  # noqa: UP047 - the project's mypy target predates PEP 695
    start: Callable[[], Awaitable[_T]],
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_seconds: float = DISCONNECT_POLL_SECONDS,
) -> _T:
    """Await ``start()``, but stop it when ``is_disconnected()`` turns true; raises :class:`AnalysisCancelledError`.

    The cancelled run is awaited to its end so its ``finally`` blocks (the scratch-prefix delete) run before this
    returns. Whatever ``start()`` raises on its own is raised unchanged.
    """
    event = threading.Event()
    token = _CANCEL.set(event)
    try:
        task = asyncio.ensure_future(start())  # the task copies the context, so it sees ``event``
    finally:
        _CANCEL.reset(token)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=poll_seconds)
            if not task.done() and await is_disconnected():
                event.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise AnalysisCancelledError("the caller of the analysis disconnected")
        return task.result()
    finally:
        if not task.done():  # this coroutine itself was cancelled (the server dropped the handler)
            event.set()
            task.cancel()
