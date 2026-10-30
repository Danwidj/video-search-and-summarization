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

"""The worker mounts ``POST /api/v1/incidents/synthesize``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
import pytest

from vss_agents.api.custom_fastapi_worker import CustomFastApiFrontEndWorker


@pytest.fixture(autouse=True)
def _stub_sibling_routes():
    """Stub every other register fn so only the synthesise mount runs for real."""
    names = [
        "register_video_upload",
        "register_video_upload_complete",
        "register_video_search_ingest_routes",
        "register_rtsp_ingest_routes",
        "register_rtsp_delete_routes",
        "register_video_delete_routes",
        "register_incident_analyze_routes",
        "register_incident_search_routes",
        "register_incident_revision_search_routes",
        "register_incident_chat_routes",
        "register_incident_evidence_embeddings_routes",
        "register_incident_match_judge_routes",
    ]
    patches = [patch(f"vss_agents.api.custom_fastapi_worker.{name}") for name in names]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _mounted_app(functions: dict) -> FastAPI:
    worker = CustomFastApiFrontEndWorker.__new__(CustomFastApiFrontEndWorker)
    config = MagicMock()
    config.general.front_end.streaming_ingest = MagicMock(model_extra={})
    config.functions = functions
    worker._config = config
    app = FastAPI()
    worker._register_streaming_routes(app, MagicMock())
    return app


def _paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_worker_exposes_synthesize_route():
    app = _mounted_app({})
    assert "/api/v1/incidents/synthesize" in _paths(app)


def test_worker_exposes_link_evidence_route():
    assert "/api/v1/incidents/link-evidence" in _paths(_mounted_app({}))


def test_synthesize_reads_rp1_url_from_incident_report_gen(monkeypatch):
    monkeypatch.setenv("SYNTH_TEST_KEY", "k")
    cfg = SimpleNamespace(rp1_base_url="http://rp1.example", api_key_env="SYNTH_TEST_KEY")
    app = _mounted_app({"incident_report_gen": cfg})
    assert "/api/v1/incidents/synthesize" in _paths(app)
