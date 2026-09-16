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

"""Upload/analyze orchestration + status-polling helpers, driven against the
hermetic SQLite fixture directly - no AppTest, since dialogs and timed
``st.fragment`` reruns aren't something AppTest can drive.
"""

from __future__ import annotations

from agent_client import Result
from catalog_actions import current_status, derive_video_id, should_keep_polling, upload_and_record
from db import IncidentDB


class _FakeAgent:
    def __init__(self, result: Result) -> None:
        self._result = result

    def upload_video(self, *, filename: str, content: bytes) -> Result:  # noqa: ARG002
        return self._result


def test_derive_video_id_fits_the_videos_id_column():
    # A sensor_id at the agent's own max length (128 chars) must still map to
    # something that fits `videos.id` (String(20)).
    long_sensor_id = "sensor-" + "a" * 121
    video_id = derive_video_id(long_sensor_id)
    assert len(video_id) <= 20


def test_derive_video_id_is_deterministic():
    assert derive_video_id("sensor-abc123") == derive_video_id("sensor-abc123")
    assert derive_video_id("sensor-abc123") != derive_video_id("sensor-xyz789")


def test_upload_and_record_creates_a_video_row_on_success(incident_db: IncidentDB):
    agent = _FakeAgent(Result(ok=True, data={"sensor_id": "sensor-abc123", "filepath": "http://vst/clip.mp4"}))
    result = upload_and_record(agent, incident_db, filename="clip.mp4", content=b"bytes")

    assert result.ok is True
    video_id = result.data
    row = incident_db.get_video(video_id)
    # videos.filepath stores the categorized R2 object key, which is only known
    # after analyze chooses the incident type and uploads the bytes to R2.
    assert row["filepath"] is None
    assert row["source"] == "sensor-abc123"


def test_upload_and_record_creates_no_row_on_failure(incident_db: IncidentDB):
    agent = _FakeAgent(Result(ok=False, error="boom"))
    result = upload_and_record(agent, incident_db, filename="clip.mp4", content=b"bytes")

    assert result.ok is False
    assert incident_db.list_videos() == []


def test_upload_and_record_creates_no_row_when_not_implemented(incident_db: IncidentDB):
    agent = _FakeAgent(Result(ok=False, not_implemented=True, status_code=404, error="not implemented"))
    result = upload_and_record(agent, incident_db, filename="clip.mp4", content=b"bytes")

    assert result.ok is False
    assert result.not_implemented is True
    assert incident_db.list_videos() == []


def test_status_polling_reflects_a_mid_test_fixture_change(incident_db: IncidentDB):
    incident_db.upsert_video("v-test1234567890abcd", filepath="http://vst/clip.mp4", source="sensor-abc")

    assert current_status(incident_db, "v-test1234567890abcd") == "unanalyzed"
    assert should_keep_polling("unanalyzed") is True

    # Simulate `/analyze` landing and recording an incident against the video.
    incident_db.insert_model_run("run-1", model_name="test-model")
    incident_db.insert_incident("v-test1234567890abcd", "run-1")

    new_status = current_status(incident_db, "v-test1234567890abcd")
    assert new_status == "unreviewed"
    assert should_keep_polling(new_status) is False
