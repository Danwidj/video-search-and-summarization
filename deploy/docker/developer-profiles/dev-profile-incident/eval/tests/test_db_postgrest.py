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

"""Supabase API key headers: a legacy JWT key is also a bearer token; a new
``sb_secret_...`` key is not a JWT and goes in ``apikey`` only."""

from __future__ import annotations

from db_postgrest import PostgrestIncidentDB, auth_headers

JWT_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJlLV8"
SECRET_KEY = "sb_secret_AbCdEf0123456789_-xyz"


def test_auth_headers_send_a_bearer_token_only_for_a_jwt_key():
    assert auth_headers(JWT_KEY) == {"apikey": JWT_KEY, "Authorization": f"Bearer {JWT_KEY}"}
    assert auth_headers(SECRET_KEY) == {"apikey": SECRET_KEY}
    assert auth_headers("a.b") == {"apikey": "a.b"}
    assert auth_headers("a.b.c.d") == {"apikey": "a.b.c.d"}


def test_client_requests_carry_the_headers_for_its_key():
    for key, authorization in ((JWT_KEY, f"Bearer {JWT_KEY}"), (SECRET_KEY, None)):
        db = PostgrestIncidentDB("https://supabase.test/", key)
        try:
            headers = db._client.headers
            assert headers["apikey"] == key
            assert headers.get("authorization") == authorization
            assert headers["content-type"] == "application/json"
            assert str(db._client.base_url) == "https://supabase.test/rest/v1/"
        finally:
            db._client.close()
