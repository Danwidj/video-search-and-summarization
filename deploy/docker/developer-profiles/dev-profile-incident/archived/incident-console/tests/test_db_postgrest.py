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

from __future__ import annotations

import json

import httpx
import pytest

from db_postgrest import PostgrestError, PostgrestIncidentDB


def test_insert_incident_calls_rpc_endpoint():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if request.url.path == "/rest/v1/rpc/insert_incident":
            return httpx.Response(200, json=None)
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)
    client = PostgrestIncidentDB("http://supabase-mock", "test-key")
    client._client = httpx.Client(base_url="http://supabase-mock/rest/v1", transport=transport)

    fields = {
        "type": "burglary",
        "start_timestamp": "0:05",
        "end_timestamp": "0:25",
        "duration": 20,
        "description": "Forced entry detected",
        "severity_level": 3,
        "confidence_score": 0.88,
    }

    res_inc, res_run = client.insert_incident("v123", "run456", fields=fields)
    assert res_inc == "v123"
    assert res_run == "run456"

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.method == "POST"
    assert req.url.path == "/rest/v1/rpc/insert_incident"
    body = json.loads(req.content)
    assert body == {
        "p_incident_id": "v123",
        "p_model_run_id": "run456",
        "p_type": "burglary",
        "p_start_timestamp": "0:05",
        "p_end_timestamp": "0:25",
        "p_duration": 20,
        "p_description": "Forced entry detected",
        "p_severity_level": 3,
        "p_confidence_score": 0.88,
    }


def test_rpc_raises_postgrest_error_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal DB error")

    transport = httpx.MockTransport(handler)
    client = PostgrestIncidentDB("http://supabase-mock", "test-key")
    client._client = httpx.Client(base_url="http://supabase-mock/rest/v1", transport=transport)

    with pytest.raises(PostgrestError) as exc_info:
        client._rpc("insert_incident", {"p_incident_id": "v1"})
    assert "RPC insert_incident -> 500: Internal DB error" in str(exc_info.value)
