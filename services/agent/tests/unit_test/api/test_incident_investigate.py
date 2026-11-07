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

"""Unit tests for ``POST /api/v1/incidents/{video_id}/investigate`` (a fake agent, no model, no network)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vss_agents.api.incident_investigate import ENABLED_ENV
from vss_agents.api.incident_investigate import register_incident_investigate_routes
from vss_agents.utils import agent_loop

URL = "/api/v1/incidents/V1/investigate"
BODY = {"question": "who gets out of the car?"}


class _Runner:
    def __init__(self, script):
        self.script = script

    async def result(self, to_type=str):
        return await self.script()


class _SessionManager:
    def __init__(self, script):
        self.script = script
        self.questions: list[str] = []

    @asynccontextmanager
    async def run(self, question):
        self.questions.append(question)
        yield _Runner(self.script)


async def _ok() -> str:
    return "ok"


async def _calls(*tools: tuple[str, dict], final: str = "A person."):
    for name, args in tools:
        await agent_loop.run_guarded_tool(name, args, _ok)
    return final


def _client(script, *, factory=None) -> tuple[TestClient, _SessionManager, AsyncMock]:
    manager = _SessionManager(script)
    create = factory or AsyncMock(return_value=manager)
    app = FastAPI()
    register_incident_investigate_routes(app, MagicMock(), create)
    return TestClient(app), manager, create


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "1")


def test_off_by_default_is_a_404_and_the_agent_is_never_built(monkeypatch) -> None:
    monkeypatch.delenv(ENABLED_ENV, raising=False)
    client, _, create = _client(lambda: _calls())
    assert client.post(URL, json=BODY).status_code == 404
    create.assert_not_called()


def test_the_flag_is_read_on_every_request(monkeypatch) -> None:
    client, _, _ = _client(lambda: _calls())
    monkeypatch.setenv(ENABLED_ENV, "true")
    assert client.post(URL, json=BODY).status_code == 200
    monkeypatch.setenv(ENABLED_ENV, "off")
    assert client.post(URL, json=BODY).status_code == 404


def test_answer_steps_and_actions(on) -> None:
    client, manager, create = _client(
        lambda: _calls(
            ("incident_read_report", {}),
            ("propose_rename", {"key": "k1", "label": "white van"}),
            final="Renamed.",
        )
    )
    reply = client.post(URL, json=BODY)
    data = reply.json()
    assert reply.status_code == 200
    assert data["status"] == "ok"
    assert data["answer"] == "Renamed."
    assert [s["tool"] for s in data["steps"]] == ["incident_read_report", "propose_rename"]
    assert data["actions"] == [{"tool": "propose_rename", "args": {"key": "k1", "label": "white van"}}]
    assert manager.questions == [BODY["question"]]
    create.assert_awaited_once()
    assert create.await_args.args[1] == "investigator"


def test_the_session_manager_is_made_once(on) -> None:
    client, _, create = _client(lambda: _calls())
    client.post(URL, json=BODY)
    client.post(URL, json=BODY)
    create.assert_awaited_once()


def test_reaching_the_iteration_cap_is_not_ok(on) -> None:
    cap = f"{agent_loop.CAP_ANSWER_PREFIX} 4 iterations. The agent repeatedly called tools."
    client, _, _ = _client(lambda: _calls(("a", {}), final=cap))
    data = client.post(URL, json=BODY).json()
    assert data["status"] == "cap_reached"
    assert len(data["steps"]) == 1


def test_a_sixth_tool_step_aborts_the_run(on) -> None:
    client, _, _ = _client(lambda: _calls(*[(f"t{i}", {}) for i in range(8)]))
    data = client.post(URL, json=BODY).json()
    assert data["status"] == "aborted:step_budget"
    assert len(data["steps"]) == 5


def test_an_agent_that_is_not_declared_is_a_501(on) -> None:
    client, _, _ = _client(lambda: _calls(), factory=AsyncMock(side_effect=ValueError("no such function")))
    assert client.post(URL, json=BODY).status_code == 501


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "x" * 501}, {"question": "q", "video_id": "V2"}])
def test_a_bad_body_is_a_422(on, body) -> None:
    client, _, _ = _client(lambda: _calls())
    assert client.post(URL, json=body).status_code == 422
