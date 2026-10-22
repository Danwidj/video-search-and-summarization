# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``POST /api/v1/incidents/chat`` with SearchClient fakes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from vss_agents.api.incident_chat import AssistantMessage
from vss_agents.api.incident_chat import ChatRequest
from vss_agents.api.incident_chat import ChatResponse
from vss_agents.api.incident_chat import register_incident_chat_routes

CONTRACTS_DIR = Path(__file__).resolve().parents[5] / "deploy/docker/developer-profiles/dev-profile-incident/contracts"
CHAT_RESPONSE_SCHEMA = json.loads(
    (CONTRACTS_DIR / "chat-contract-v1" / "chat_response.schema.json").read_text(encoding="utf-8")
)
response_validator = Draft202012Validator(CHAT_RESPONSE_SCHEMA)


class FakeSearchClient:
    """Configurable fake SearchClient for unit tests."""

    def __init__(
        self,
        hits: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.hits = hits if hits is not None else []
        self.error = error
        self.last_query: str | None = None
        self.last_filters: dict[str, Any] | None = None

    async def search(
        self,
        query: str,
        top_k: int = 5,
        item_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_query = query
        self.last_filters = filters
        if self.error:
            raise self.error
        return self.hits[:top_k]


def _make_client(search_client=None) -> TestClient:
    app = FastAPI()
    register_incident_chat_routes(app, search_client=search_client)
    return TestClient(app)


def test_chat_minimal_request_returns_grounded_answer():
    client = _make_client()
    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "What weapon was brandished in the altercation?"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["message"]["role"] == "assistant"
    assert len(data["message"]["citations"]) > 0
    cit = data["message"]["citations"][0]
    assert cit["item_id"] == "I1"
    assert cit["item_type"] == "instrument"
    assert cit["incident_id"] == "Assault007"
    assert "machete" in data["message"]["content"].lower()

    # Validate against chat-contract-v1 JSON Schema
    errors = list(response_validator.iter_errors(data))
    assert not errors, f"Response failed chat-contract-v1 schema: {errors}"


def test_chat_with_custom_search_client_fake():
    fake_hit = {
        "result_id": "res_custom_1",
        "rank": 1,
        "similarity_score": 0.95,
        "item": {
            "item_type": "instrument",
            "item_id": "I99",
            "name": "hammer",
            "label": "hammer",
            "description": "Claw hammer dropped on sidewalk",
            "threat_level": 3,
            "crop_image_url": "https://pub-r2.example.com/evidence/V1/MR1/instruments/I99.jpg",
            "timestamp_seconds": 42.0,
        },
        "incident": {
            "incident_id": "V1",
            "incident_type": "burglary",
            "title": "Hardware store break-in",
        },
    }
    fake_client = FakeSearchClient(hits=[fake_hit])
    client = _make_client(search_client=fake_client)

    resp = client.post(
        "/api/v1/incidents/chat",
        json={
            "session_id": "session_test_abc",
            "messages": [{"role": "user", "content": "What tools were found?"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "session_test_abc"
    assert fake_client.last_query == "What tools were found?"
    assert len(data["message"]["citations"]) == 1
    assert data["message"]["citations"][0]["item_id"] == "I99"
    assert data["message"]["citations"][0]["timestamp_seconds"] == 42.0
    assert "hammer" in data["message"]["content"]


def test_chat_empty_results_cleanly_handled():
    fake_client = FakeSearchClient(hits=[])
    client = _make_client(search_client=fake_client)

    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "Did an extraterrestrial land?"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"]["citations"] == []
    assert "No matching incidents or evidence items were found" in data["message"]["content"]

    # Validate against chat-contract-v1 schema
    errors = list(response_validator.iter_errors(data))
    assert not errors, f"Empty response failed schema: {errors}"


def test_chat_incident_scope_filters_by_incident_id():
    fake_client = FakeSearchClient(hits=[])
    client = _make_client(search_client=fake_client)

    resp = client.post(
        "/api/v1/incidents/chat",
        json={
            "messages": [{"role": "user", "content": "What did you see?"}],
            "context": {"scope": "incident", "incident_id": "Assault007"},
        },
    )
    assert resp.status_code == 200
    assert fake_client.last_filters == {"incident_id": "Assault007"}


def test_chat_search_client_error_returns_502():
    fake_client = FakeSearchClient(error=RuntimeError("Connection refused to vector store"))
    client = _make_client(search_client=fake_client)

    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "Any knives?"}]},
    )
    assert resp.status_code == 502
    assert "Evidence search error" in resp.json()["detail"]


def test_chat_missing_user_message_returns_400():
    client = _make_client()
    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "assistant", "content": "Hello user"}]},
    )
    assert resp.status_code == 400
    assert "At least one message with role 'user' is required" in resp.json()["detail"]


def test_chat_empty_user_message_returns_400():
    client = _make_client()
    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "   "}]},
    )
    assert resp.status_code == 400
    assert "must not be empty" in resp.json()["detail"]


def test_chat_invalid_scope_returns_422():
    client = _make_client()
    resp = client.post(
        "/api/v1/incidents/chat",
        json={
            "messages": [{"role": "user", "content": "weapons?"}],
            "context": {"scope": "invalid_scope"},
        },
    )
    assert resp.status_code == 422


def test_chat_multi_turn_history_uses_latest_user_message():
    fake_client = FakeSearchClient(hits=[])
    client = _make_client(search_client=fake_client)

    resp = client.post(
        "/api/v1/incidents/chat",
        json={
            "messages": [
                {"role": "user", "content": "First question about cars"},
                {"role": "assistant", "content": "No cars found"},
                {"role": "user", "content": "Second question about crowbars"},
            ]
        },
    )
    assert resp.status_code == 200
    assert fake_client.last_query == "Second question about crowbars"


FIXTURES_DIR = CONTRACTS_DIR / "chat-contract-v1" / "fixtures"


def _fixtures(kind: str, prefix: str) -> list[Path]:
    return sorted((FIXTURES_DIR / kind).glob(f"{prefix}*.json"))


def _fixture_id(path: Path) -> str:
    return path.name


@pytest.mark.parametrize(
    "path", _fixtures("valid", "full-request") + _fixtures("valid", "minimal-request"), ids=_fixture_id
)
def test_models_accept_valid_request_fixtures(path: Path):
    ChatRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", _fixtures("invalid", "request-"), ids=_fixture_id)
def test_models_reject_invalid_request_fixtures(path: Path):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "path", _fixtures("valid", "full-response") + _fixtures("valid", "empty-response"), ids=_fixture_id
)
def test_models_accept_valid_response_fixtures(path: Path):
    ChatResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", _fixtures("invalid", "response-"), ids=_fixture_id)
def test_models_reject_invalid_response_fixtures(path: Path):
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_assistant_message_requires_citations():
    with pytest.raises(ValidationError):
        AssistantMessage.model_validate({"role": "assistant", "content": "hi"})
