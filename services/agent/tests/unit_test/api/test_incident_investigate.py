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

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import openai
import pytest

from vss_agents.api.incident_investigate import create_incident_investigate_router
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


def test_answer_steps_and_actions() -> None:
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


def test_the_session_manager_is_made_once() -> None:
    client, _, create = _client(lambda: _calls())
    client.post(URL, json=BODY)
    client.post(URL, json=BODY)
    create.assert_awaited_once()


def test_reaching_the_iteration_cap_is_not_ok() -> None:
    cap = f"{agent_loop.CAP_ANSWER_PREFIX} 4 iterations. The agent repeatedly called tools."
    client, _, _ = _client(lambda: _calls(("a", {}), final=cap))
    data = client.post(URL, json=BODY).json()
    assert data["status"] == "cap_reached"
    assert len(data["steps"]) == 1
    assert data["answer"] == "The agent reached its tool step limit before it could answer; no changes were proposed."


def test_a_sixth_tool_step_aborts_the_run() -> None:
    client, _, _ = _client(lambda: _calls(*[(f"t{i}", {}) for i in range(8)]))
    data = client.post(URL, json=BODY).json()
    assert data["status"] == "aborted:step_budget"
    assert len(data["steps"]) == 5


def test_an_agent_that_is_not_declared_is_a_501() -> None:
    client, _, _ = _client(lambda: _calls(), factory=AsyncMock(side_effect=ValueError("no such function")))
    assert client.post(URL, json=BODY).status_code == 501


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "x" * 501}, {"question": "q", "video_id": "V2"}])
def test_a_bad_body_is_a_422(body) -> None:
    client, _, _ = _client(lambda: _calls())
    assert client.post(URL, json=body).status_code == 422


DRAFT = {"incident": {"title": "Fight"}, "entities": [{"key": "p1", "type": "human"}]}


def test_a_draft_runs_the_editor_agent_with_the_draft_in_its_question() -> None:
    seen: list = []

    async def script() -> str:
        seen.append(agent_loop.current().draft)
        return await _calls(("propose_delete_item", {"item_key": "p1"}), final="Deleted.")

    client, manager, create = _client(script)
    data = client.post(URL, json={**BODY, "draft": DRAFT}).json()
    assert create.await_args.args[1] == "report_editor"
    assert data["actions"] == [{"tool": "propose_delete_item", "args": {"item_key": "p1"}}]
    assert manager.questions[0].startswith(BODY["question"])
    assert '"key":"p1"' in manager.questions[0]
    assert seen[0].entities[0].key == "p1"


def test_a_new_evidence_request_opens_the_box_tool_from_the_reviewers_message_with_no_question() -> None:
    client, manager, _ = _client(
        lambda: _calls(("propose_open_box_tool", {"seconds": 12, "name": "Bag on floor"}), final="Opening it.")
    )
    history = [{"role": "user", "text": "I want to add a new evidence item, a bag on the floor"}]
    data = client.post(URL, json={**BODY, "draft": DRAFT, "history": history}).json()
    assert data["actions"] == [{"tool": "propose_open_box_tool", "args": {"seconds": 12, "name": "Bag on floor"}}]
    assert "user: I want to add a new evidence item, a bag on the floor" in manager.questions[0]
    assert "questions asked" not in manager.questions[0]


def test_the_recent_chat_goes_into_the_editor_input_oldest_first() -> None:
    client, manager, _ = _client(lambda: _calls(final="Done."))
    history = [
        {"role": "user", "text": "Who is on the left?"},
        {"role": "assistant", "text": "E1, the person in purple."},
    ]
    assert client.post(URL, json={**BODY, "draft": DRAFT, "history": history}).status_code == 200
    question = manager.questions[0]
    assert question.index("user: Who is on the left?") < question.index("assistant: E1, the person in purple.")


def test_a_draft_with_reviewer_labels_is_accepted_and_reaches_the_editor() -> None:
    draft = {
        "incident": {"title": "Fight"},
        "entities": [{"key": "p1", "type": "human", "reviewer_label": "E1", "reviewer_name": "person in purple"}],
    }
    client, manager, _ = _client(lambda: _calls(final="Done."))
    assert client.post(URL, json={**BODY, "draft": draft}).status_code == 200
    assert '"reviewer_label":"E1"' in manager.questions[0]


def test_the_chat_history_without_a_draft_is_not_sent_to_the_investigator() -> None:
    client, manager, _ = _client(lambda: _calls(final="An answer."))
    history = [{"role": "user", "text": "Earlier question"}]
    assert client.post(URL, json={**BODY, "history": history}).status_code == 200
    assert manager.questions[0] == BODY["question"]


def test_more_than_six_history_turns_is_a_422() -> None:
    client, _, _ = _client(_ok)
    history = [{"role": "user", "text": f"turn {n}"} for n in range(7)]
    assert client.post(URL, json={**BODY, "draft": DRAFT, "history": history}).status_code == 422


def test_the_retired_evidence_exchange_field_is_a_422() -> None:
    client, _, _ = _client(lambda: _calls())
    evidence = {"questions_asked": 1, "transcript": []}
    assert client.post(URL, json={**BODY, "draft": DRAFT, "evidence": evidence}).status_code == 422


def test_a_request_without_a_draft_still_runs_the_investigator() -> None:
    client, manager, create = _client(lambda: _calls())
    client.post(URL, json=BODY)
    assert create.await_args.args[1] == "investigator"
    assert manager.questions == [BODY["question"]]


def test_each_agent_gets_its_own_session_manager() -> None:
    client, _, create = _client(lambda: _calls())
    client.post(URL, json=BODY)
    client.post(URL, json={**BODY, "draft": DRAFT})
    client.post(URL, json={**BODY, "draft": DRAFT})
    assert [call.args[1] for call in create.await_args_list] == ["investigator", "report_editor"]


def test_a_draft_with_a_repeated_key_is_a_422() -> None:
    client, _, _ = _client(lambda: _calls())
    twin = {"incident": {}, "entities": [{"key": "a"}, {"key": "a"}]}
    assert client.post(URL, json={**BODY, "draft": twin}).status_code == 422


def _client_with_wall(script, *, wall_seconds: float) -> TestClient:
    manager = _SessionManager(script)
    app = FastAPI()
    app.include_router(
        create_incident_investigate_router(MagicMock(), AsyncMock(return_value=manager), wall_seconds=wall_seconds)
    )
    return TestClient(app)


def test_a_run_that_hits_the_step_limit_answers_with_a_sentence_counting_its_changes() -> None:
    client, _, _ = _client(lambda: _calls(*[("propose_rename", {"key": f"k{i}", "label": "van"}) for i in range(8)]))
    data = client.post(URL, json=BODY).json()
    assert data["status"] == "aborted:step_budget"
    assert data["answer"] == "The agent reached its tool step limit before it could answer; 5 changes were proposed."
    assert len(data["actions"]) == 5


def test_a_run_past_the_wall_clock_answers_with_a_sentence() -> None:
    async def stalled() -> str:
        await asyncio.sleep(30)
        return "never"

    data = _client_with_wall(stalled, wall_seconds=0.05).post(URL, json=BODY).json()
    assert data["status"] == "timeout"
    assert data["answer"] == "The agent ran out of time before it could answer; no changes were proposed."


def test_a_busy_model_answers_with_a_sentence() -> None:
    async def busy() -> str:
        raise openai.RateLimitError(
            "slow down", response=httpx.Response(429, request=httpx.Request("POST", "http://m")), body=None
        )

    data = _client(busy)[0].post(URL, json=BODY).json()
    assert data["status"] == "busy"
    assert data["answer"] == "The model is busy, so the agent could not answer; no changes were proposed."


def test_an_error_answers_with_a_sentence_and_the_next_question_is_answered() -> None:
    outcomes = [RuntimeError("tool crashed"), "Two people."]

    async def script() -> str:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client, _, _ = _client(script)
    first = client.post(URL, json=BODY).json()
    assert first["status"] == "error"
    assert first["answer"] == "The agent hit an error before it could answer; no changes were proposed."
    second = client.post(URL, json=BODY)
    assert second.status_code == 200
    assert second.json()["answer"] == "Two people."
