# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for mock POST /api/v1/incidents/chat endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from base_profile_mock.app import create_app


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
            "context": {"scope": "incident", "incident_id": "Burglary004"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "session_mock_1"
    assert len(data["message"]["citations"]) > 0
    for cit in data["message"]["citations"]:
        assert "Burglary004" in cit["incident_id"]


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
