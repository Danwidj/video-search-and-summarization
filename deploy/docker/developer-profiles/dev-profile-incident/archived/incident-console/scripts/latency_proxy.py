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

"""A tiny TCP proxy that counts network round trips and injects latency.

Dev tooling for ``measure_db_roundtrips.py``; stdlib only, protocol-agnostic
(it never parses Postgres).

* **Round trip**: a burst of client->server bytes that is answered by
  server->client bytes. Pipelined requests inside one burst count once, exactly
  as the network would see them; a trailing ``Terminate`` with no reply does not
  count.
* **Latency**: every chunk is held for ``rtt_ms / 2`` in each direction, so one
  round trip costs ``rtt_ms`` of wall-clock. Order is preserved per direction;
  bandwidth is not modelled.

TLS is not modelled: point the client at the proxy with ``sslmode=disable`` (a
real remote handshake costs extra round trips on top of what is counted here).
"""

from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
from typing import Literal

Upstream = str | tuple[str, int]
_CHUNK = 65536


class LatencyProxy:
    """Listen on ``127.0.0.1:<ephemeral>`` and relay to ``upstream`` (a Unix-socket path or ``(host, port)``)."""

    def __init__(self, upstream: Upstream, *, rtt_ms: float = 0.0, host: str = "127.0.0.1") -> None:
        self.upstream = upstream
        self.rtt_ms = rtt_ms
        self._lock = threading.Lock()
        self._round_trips = 0
        self._sessions: list[_Session] = []
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((host, 0))
        self._listener.listen(16)
        self.host, self.port = self._listener.getsockname()
        self._closed = False
        threading.Thread(target=self._accept_loop, name="latency-proxy-accept", daemon=True).start()

    # -- stats ------------------------------------------------------------ #
    @property
    def round_trips(self) -> int:
        with self._lock:
            return self._round_trips

    def _count_round_trip(self) -> None:
        with self._lock:
            self._round_trips += 1

    @property
    def one_way_seconds(self) -> float:
        return max(self.rtt_ms, 0.0) / 2000.0

    # -- lifecycle -------------------------------------------------------- #
    def _accept_loop(self) -> None:
        while not self._closed:
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            try:
                session = _Session(self, client)
            except OSError:
                client.close()
                continue
            self._sessions.append(session)
            session.start()

    def close(self) -> None:
        self._closed = True
        with contextlib.suppress(OSError):
            self._listener.close()
        for session in list(self._sessions):
            session.close()

    def __enter__(self) -> LatencyProxy:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _Session:
    """One client connection: two reader threads and two delayed writer threads."""

    def __init__(self, proxy: LatencyProxy, client: socket.socket) -> None:
        self.proxy = proxy
        self.client = client
        if isinstance(proxy.upstream, str):
            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.connect(proxy.upstream)
        else:
            self.server = socket.create_connection(proxy.upstream)
            self.server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._last: Literal["C", "S", ""] = ""
        self._last_lock = threading.Lock()
        self._open = 2

    def start(self) -> None:
        for src, dst, side in ((self.client, self.server, "C"), (self.server, self.client, "S")):
            delayed: queue.Queue[tuple[float, bytes] | None] = queue.Queue()
            threading.Thread(target=self._read, args=(src, delayed, side), daemon=True).start()
            threading.Thread(target=self._write, args=(dst, delayed), daemon=True).start()

    def _note(self, side: Literal["C", "S"]) -> None:
        with self._last_lock:
            # A reply that follows client bytes closes one round trip.
            if side == "S" and self._last == "C":
                self.proxy._count_round_trip()
            self._last = side

    def _read(self, src: socket.socket, delayed: queue.Queue, side: Literal["C", "S"]) -> None:
        try:
            while data := src.recv(_CHUNK):
                self._note(side)
                delayed.put((time.monotonic() + self.proxy.one_way_seconds, data))
        except OSError:
            pass
        finally:
            delayed.put(None)

    def _write(self, dst: socket.socket, delayed: queue.Queue) -> None:
        try:
            while (item := delayed.get()) is not None:
                due, data = item
                if (wait := due - time.monotonic()) > 0:
                    time.sleep(wait)
                dst.sendall(data)
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        finally:
            with self._last_lock:
                self._open -= 1
                done = self._open == 0
            if done:
                self.close()

    def close(self) -> None:
        for sock in (self.client, self.server):
            with contextlib.suppress(OSError):
                sock.close()
