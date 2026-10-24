# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for mock POST /api/v1/incidents/chat endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from base_profile_mock.app import create_app
from base_profile_mock.routers.incident_chat import ChatRequest
from base_profile_mock.routers.incident_chat import ChatResponse

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "contracts" / "chat-contract-v1" / "fixtures"


def test_mock_chat_minimal_request_returns_200():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "What weapon was used?"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["message"]["role"] == "assistant"
    assert len(data["message"]["citations"]) > 0
    cit = data["message"]["citations"][0]
    assert "incident_id" in cit
    assert "item_id" in cit
    assert "item_type" in cit
    assert "timestamp_seconds" in cit
    assert "crop_image_url" in cit


def test_mock_chat_scoped_to_incident():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat",
        json={
            "session_id": "session_mock_1",
            "messages": [{"role": "user", "content": "Tell me about instruments"}],
            "context": {"scope": "incident", "incident_id": "Assault032"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "session_mock_1"
    assert len(data["message"]["citations"]) > 0
    for cit in data["message"]["citations"]:
        assert "Assault032" in cit["incident_id"]


def test_mock_chat_empty_results():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "Did a spaceship land?"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"]["citations"] == []
    assert "No matching incidents" in data["message"]["content"]


def test_mock_chat_rejects_missing_messages():
    client = TestClient(create_app())
    resp = client.post("/api/v1/incidents/chat", json={})
    assert resp.status_code == 422


def test_mock_chat_rejects_empty_messages():
    client = TestClient(create_app())
    resp = client.post("/api/v1/incidents/chat", json={"messages": []})
    assert resp.status_code == 422


def test_mock_chat_rejects_invalid_scope():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat",
        json={
            "messages": [{"role": "user", "content": "weapons?"}],
            "context": {"scope": "interstellar"},
        },
    )
    assert resp.status_code == 422


def test_mock_chat_rejects_unknown_fields():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "weapons?"}], "extra": 1},
    )
    assert resp.status_code == 422


def test_mock_models_match_contract_fixtures():
    for path in sorted((FIXTURES_DIR / "valid").glob("*request.json")):
        ChatRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted((FIXTURES_DIR / "valid").glob("*response.json")):
        ChatResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted((FIXTURES_DIR / "invalid").glob("request-*.json")):
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted((FIXTURES_DIR / "invalid").glob("response-*.json")):
        with pytest.raises(ValidationError):
            ChatResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_mock_chat_accepts_version_id_and_draft_report():
    client = TestClient(create_app())
    body = {"messages": [{"role": "user", "content": "What weapon was used?"}], "version_id": 7}
    resp = client.post("/api/v1/incidents/chat", json=body)
    assert resp.status_code == 200
    assert "report version 7" in resp.json()["message"]["content"]

    resp = client.post("/api/v1/incidents/chat", json={**body, "draft_report": {"evidence": []}})
    assert resp.status_code == 200
    assert "unsaved draft of report version 7" in resp.json()["message"]["content"]


def test_mock_chat_rejects_draft_report_without_version_id():
    resp = TestClient(create_app()).post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "weapons?"}], "draft_report": {}},
    )
    assert resp.status_code == 422


def test_chat_citation_images_resolve_to_the_mock_placeholder():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat", json={"messages": [{"role": "user", "content": "What weapon was used?"}]}
    )
    url = resp.json()["message"]["citations"][0]["crop_image_url"]
    assert "example.com" not in url
    image = client.get(urlparse(url).path)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"


def test_mock_chat_answer_says_it_is_a_keyword_mock():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/chat", json={"messages": [{"role": "user", "content": "What weapon was used?"}]}
    )
    assert "mock answer, no model" in resp.json()["message"]["content"]
