"""Unit tests for ``POST /api/v1/incidents/{video_id}/evidence-asks`` (validation, no writes)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vss_agents.api.incident_evidence_asks import register_incident_evidence_asks_routes

URL = "/api/v1/incidents/vid-1/evidence-asks"
INCIDENT = {"start_timestamp": 10, "end_timestamp": 60}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_incident_evidence_asks_routes(app)
    return TestClient(app)


def test_route_proposes_the_box_tool_opening(client: TestClient) -> None:
    body = {"incident": INCIDENT, "calls": [{"tool": "open_box_tool", "args": {"seconds": 30, "name": "Bag"}}]}
    data = client.post(URL, json=body).json()
    assert [p["tool"] for p in data["proposals"]] == ["open_box_tool"]
    assert data["proposals"][0]["args"] == {"seconds": 30, "name": "Bag"}
    assert data["rejected"] == []


def test_route_refuses_a_question_to_the_reviewer(client: TestClient) -> None:
    body = {
        "incident": INCIDENT,
        "calls": [
            {"tool": "ask_reviewer", "args": {"question": "Who?"}},
            {"tool": "open_box_tool", "args": {"seconds": 30, "name": "Bag"}},
        ],
    }
    data = client.post(URL, json=body).json()
    assert [p["tool"] for p in data["proposals"]] == ["open_box_tool"]
    assert [r["tool"] for r in data["rejected"]] == ["ask_reviewer"]
    assert data["rejected"][0]["reason"] == "There is no tool called 'ask_reviewer'."


def test_route_refuses_the_question_count_the_question_step_used_to_send(client: TestClient) -> None:
    body = {"questions_asked": 0, "calls": [{"tool": "open_box_tool", "args": {"seconds": 30, "name": "Bag"}}]}
    assert client.post(URL, json=body).status_code == 422


def test_route_refuses_unknown_body_fields(client: TestClient) -> None:
    body = {"calls": [{"tool": "open_box_tool", "args": {"seconds": 30, "name": "Bag"}}], "draft": {}}
    response = client.post(URL, json=body)
    assert response.status_code == 422


def test_route_requires_at_least_one_call(client: TestClient) -> None:
    response = client.post(URL, json={"calls": []})
    assert response.status_code == 422
