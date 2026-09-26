# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from contextlib import asynccontextmanager
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

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def update_video(self, *args, **kwargs):
        self.calls.append(("video", args, kwargs))

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
    assert body["video_filepath"] == "anomaly/fighting/clip.mp4"
    assert body["incident_type"] in {"road accident", "fighting", "animal", "burglary", "explosion"}
    assert [call[0] for call in fake.calls] == ["video", "run", "incident", "entity", "report"]
    assert fake.calls[0][2] == {"filepath": "anomaly/fighting/clip.mp4"}
    assert "MOCK" in fake.calls[2][2]["fields"]["description"]


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
