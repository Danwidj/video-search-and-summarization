from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from base_profile_mock.app import create_app
from base_profile_mock.routers import incident_analyze


class FakeWriter:
    def __init__(self):
        self.calls = []

    async def get_video(self, video_id):
        return {"id": video_id}

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def insert_model_run(self, *args, **kwargs):
        self.calls.append(("run", args, kwargs))

    async def insert_incident(self, *args, **kwargs):
        self.calls.append(("incident", args, kwargs))

    async def add_incident_entity(self, *args, **kwargs):
        self.calls.append(("entity", args, kwargs))

    async def insert_generated_report(self, *args, **kwargs):
        self.calls.append(("report", args, kwargs))


def test_analyze_persists_mock_report_and_evidence(monkeypatch):
    fake = FakeWriter()
    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=lambda: fake))

    # get_db is async in production; make the fake match it.
    async def get_db():
        return fake

    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    response = TestClient(create_app()).post("/api/v1/incidents/video-1/analyze", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed" and body["mock"] is True
    assert [call[0] for call in fake.calls] == ["run", "incident", "entity", "report"]
    assert "MOCK" in fake.calls[1][2]["fields"]["description"]


def test_analyze_rejects_missing_video(monkeypatch):
    class Missing:
        async def get_video(self, _id):
            return None

    async def get_db():
        return Missing()

    # A missing id is handled before any writer transaction.
    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    response = TestClient(create_app()).post("/api/v1/incidents/video-1/analyze", json={})
    assert response.status_code == 404
