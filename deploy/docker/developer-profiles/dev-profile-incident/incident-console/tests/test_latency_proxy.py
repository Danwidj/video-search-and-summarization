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

"""The round-trip counter behind ``scripts/measure_db_roundtrips.py``, checked against a plain echo server."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from scripts.latency_proxy import LatencyProxy


@pytest.fixture
def echo_server():
    """A TCP server that answers every received chunk with ``b"re:" + chunk``."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def serve() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            threading.Thread(target=_echo, args=(conn,), daemon=True).start()

    def _echo(conn: socket.socket) -> None:
        with conn:
            while data := conn.recv(4096):
                conn.sendall(b"re:" + data)

    threading.Thread(target=serve, daemon=True).start()
    yield listener.getsockname()
    listener.close()


def request(client: socket.socket, payload: bytes) -> bytes:
    client.sendall(payload)
    return client.recv(4096)


def test_each_answered_request_is_one_round_trip(echo_server):
    with LatencyProxy(echo_server) as proxy, socket.create_connection((proxy.host, proxy.port)) as client:
        assert proxy.round_trips == 0
        assert request(client, b"a") == b"re:a"
        assert proxy.round_trips == 1
        assert request(client, b"b") == b"re:b"
        assert request(client, b"c") == b"re:c"
        assert proxy.round_trips == 3


def test_a_trailing_message_without_a_reply_is_not_a_round_trip(echo_server):
    """Postgres clients end with a Terminate message the server never answers."""
    proxy = LatencyProxy(echo_server)
    try:
        with socket.create_connection((proxy.host, proxy.port)) as client:
            request(client, b"query")
        time.sleep(0.1)  # let the proxy see the close
        assert proxy.round_trips == 1
    finally:
        proxy.close()


def test_latency_is_injected_once_per_direction(echo_server):
    with LatencyProxy(echo_server, rtt_ms=120) as proxy, socket.create_connection((proxy.host, proxy.port)) as client:
        started = time.perf_counter()
        request(client, b"x")
        elapsed = time.perf_counter() - started
    assert 0.11 <= elapsed < 0.4  # one full RTT for one round trip, not a multiple of it


def test_the_rtt_can_change_between_requests(echo_server):
    with LatencyProxy(echo_server) as proxy, socket.create_connection((proxy.host, proxy.port)) as client:
        started = time.perf_counter()
        request(client, b"fast")
        fast = time.perf_counter() - started

        proxy.rtt_ms = 100
        started = time.perf_counter()
        request(client, b"slow")
        slow = time.perf_counter() - started
    assert fast < 0.05
    assert slow >= 0.09


def test_connections_are_counted_together(echo_server):
    with LatencyProxy(echo_server) as proxy:
        for _ in range(2):
            with socket.create_connection((proxy.host, proxy.port)) as client:
                request(client, b"hi")
        assert proxy.round_trips == 2
