# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from base_profile_mock.app import create_app
from base_profile_mock.routers import incident_analyze
from base_profile_mock.state import get_state


class FakeWriter:
    def __init__(self):
        self.calls = []

    async def get_video(self, video_id):
        return {"id": video_id, "source": "sensor-1"}

    async def update_video(self, *args, **kwargs):
        self.calls.append(("video", args, kwargs))

    async def insert_model_run(self, *args, **kwargs):
        self.calls.append(("run", args, kwargs))

    async def insert_model_run_if_absent(self, *args, **kwargs):
        self.calls.append(("run_if_absent", args, kwargs))

    async def insert_ai_revision(self, *args, **kwargs):
        self.calls.append(("revision", args, kwargs))
        return {"id": 42}

    async def get_revision(self, revision_id):
        return {
            "id": revision_id,
            "evidence": [{"item_type": "entity", "item_id": "E1", "item_name": "human", "description": "a person"}],
        }


def test_analyze_inserts_mock_ai_revision(monkeypatch):
    fake = FakeWriter()

    # get_db is async in production; make the fake match it.
    async def get_db():
        return fake

    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    monkeypatch.setattr(
        incident_analyze,
        "_upload_video_to_r2",
        lambda **_kwargs: "anomaly/fighting/clip.mp4",
    )
    state = get_state()
    state.uploads.clear()
    state.streams.clear()
    state.streams["sensor-1"] = SimpleNamespace(filename="clip.mp4", content=b"video-bytes")
    response = TestClient(create_app()).post("/api/v1/incidents/video-1/analyze", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed" and body["mock"] is True
    assert body["revision_id"] == 42
    assert body["video_filepath"] == "anomaly/fighting/clip.mp4"
    assert body["incident_type"] in {"road accident", "assault", "animal attack", "burglary", "explosion"}
    assert [call[0] for call in fake.calls] == ["video", "run", "revision"]
    assert fake.calls[0][2] == {"filepath": "anomaly/fighting/clip.mp4"}
    revision = fake.calls[2]
    assert revision[1] == ("video-1",)
    assert "MOCK" in revision[2]["payload"]["incident"]["description"]
    # incident-contract-v3 types the window as integer seconds, which the facet columns are read from.
    incident = revision[2]["payload"]["incident"]
    assert (incident["start_timestamp"], incident["end_timestamp"]) == (0, 10)
    assert all(type(incident[k]) is int for k in ("start_timestamp", "end_timestamp"))
    assert revision[2]["evidence"][0]["image"] is None and revision[2]["evidence"][0]["image_gap"]
    assert revision[2]["note"] is None


def test_analyze_with_caller_run_and_reviewer_prompt(monkeypatch):
    fake = FakeWriter()

    async def get_db():
        return fake

    async def get_video(_video_id):
        return {"id": "video-1", "filepath": "anomaly/burglary/clip.mp4", "source": None}

    fake.get_video = get_video
    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    response = TestClient(create_app()).post(
        "/api/v1/incidents/video-1/analyze", json={"model_run_id": "mrun1", "reviewer_prompt": "look at the door"}
    )
    assert response.status_code == 200
    assert response.json()["model_run_id"] == "mrun1"
    assert [call[0] for call in fake.calls] == ["video", "run_if_absent", "revision"]
    assert fake.calls[2][2]["model_run_id"] == "mrun1"
    assert fake.calls[2][2]["note"] == "Reviewer prompt: look at the door"


def _analyze(monkeypatch, body, fake=None):
    fake = fake or FakeWriter()

    async def get_db():
        return fake

    async def get_video(_video_id):
        return {"id": "video-1", "filepath": "anomaly/burglary/clip.mp4", "source": None}

    fake.get_video = get_video
    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    return fake, TestClient(create_app()).post("/api/v1/incidents/video-1/analyze", json=body)


def test_analyze_accepts_allowlisted_model_and_reports_it(monkeypatch):
    model = incident_analyze._allowed_models()[0]
    fake, response = _analyze(monkeypatch, {"model_run_id": "mrun1", "model": model})
    assert response.status_code == 200
    assert response.json()["model"] == model
    assert fake.calls[1][2]["model_name"] == model


def test_analyze_rejects_model_outside_allowlist(monkeypatch):
    fake, response = _analyze(monkeypatch, {"model": "not-a-model"})
    assert response.status_code == 400
    assert "not in the incident contract allowlist" in response.json()["detail"]
    assert fake.calls == []


def test_analyze_rejects_reviewer_prompt_over_1000_characters(monkeypatch):
    fake, response = _analyze(monkeypatch, {"reviewer_prompt": "x" * 1001})
    assert response.status_code == 422
    assert fake.calls == []


def test_analyze_omitted_model_and_prompt_keep_the_mock_defaults(monkeypatch):
    fake, response = _analyze(monkeypatch, {"model_run_id": "mrun1"})
    assert response.status_code == 200
    assert response.json()["model"] == "base-profile-mock"
    assert response.json()["reviewer_prompt"] is None
    assert fake.calls[1][2]["model_name"] == "base-profile-mock"
    assert fake.calls[2][2]["note"] is None


def test_evidence_embeddings_returns_one_vector_per_item(monkeypatch):
    async def get_db():
        return FakeWriter()

    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    response = TestClient(create_app()).post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7})
    assert response.status_code == 200
    rows = response.json()
    assert [(row["item_type"], row["item_id"]) for row in rows] == [("entity", "E1")]
    assert len(rows[0]["embedding"]) == 1024


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


def test_analyze_rejects_missing_uploaded_bytes(monkeypatch):
    class MissingBytes:
        async def get_video(self, _id):
            return {"id": "video-1", "source": "sensor-missing"}

    async def get_db():
        return MissingBytes()

    state = get_state()
    state.uploads.clear()
    state.streams.clear()
    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    response = TestClient(create_app()).post("/api/v1/incidents/video-1/analyze", json={})
    assert response.status_code == 409


def test_analyze_reuses_existing_r2_object_key(monkeypatch):
    fake = FakeWriter()

    async def get_db():
        return fake

    async def get_video(_video_id):
        return {"id": "video-1", "filepath": "anomaly/burglary/clip.mp4", "source": None}

    fake.get_video = get_video
    monkeypatch.setattr(incident_analyze, "_writer_module", lambda: SimpleNamespace(get_db=get_db))
    response = TestClient(create_app()).post("/api/v1/incidents/video-1/analyze", json={})
    assert response.status_code == 200
    assert response.json()["video_filepath"] == "anomaly/burglary/clip.mp4"
    assert fake.calls[0] == ("video", ("video-1",), {"filepath": "anomaly/burglary/clip.mp4"})
    assert fake.calls[-1][0] == "revision"


def test_uploaded_bytes_are_playable_from_vst_url(monkeypatch):
    state = get_state()
    state.uploads.clear()
    state.streams.clear()
    # R2 persistence is covered by the Analyze tests; keep this endpoint test
    # focused on the mock VST's in-memory playback contract.
    from base_profile_mock.routers import vst_storage

    monkeypatch.setattr(vst_storage, "_r2_upload", lambda *_args: "uploads/sensor-test/generated.mp4")
    client = TestClient(create_app())
    response = client.post(
        "/vst/api/v1/storage/file",
        files={"mediaFile": ("clip.mp4", b"video-bytes", "video/mp4")},
        data={"filename": "clip.mp4"},
    )
    assert response.status_code == 200
    sensor_id = response.json()["sensorId"]
    playback = client.get(f"/vst/api/v1/storage/file/{sensor_id}/url")
    assert playback.status_code == 200
    video = client.get(playback.json()["videoUrl"])
    assert video.status_code == 200
    assert video.content == b"video-bytes"


def test_mock_upload_key_is_neutral_unique_and_keeps_safe_extension(monkeypatch):
    from base_profile_mock.routers import vst_storage
    from base_profile_mock.state import Stream

    values = iter(["first-id", "second-id", "fallback-id"])
    monkeypatch.setattr(vst_storage.uuid, "uuid4", lambda: next(values))
    stream = Stream(stream_id="sensor-1", name="clip", filename="incident.MP4", bytes_total=1, content=b"x")
    assert vst_storage._upload_key(stream, "sensor-1") == "uploads/sensor-1/first-id.mp4"
    assert vst_storage._upload_key(stream, "sensor-1") == "uploads/sensor-1/second-id.mp4"

    unsafe = Stream(stream_id="sensor-1", name="clip", filename="clip.not-valid!", bytes_total=1, content=b"x")
    assert vst_storage._upload_key(unsafe, "sensor-1") == "uploads/sensor-1/fallback-id.mp4"


def test_mock_categories_use_standard_incident_types() -> None:
    standard = {"road accident", "burglary", "explosion", "assault", "animal attack"}
    assert {category["type"] for category in incident_analyze._MOCK_CATEGORIES} == standard
