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

"""Unit tests for Cloudflare R2 storage and URL signing helper."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import ANY
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.utils.r2 import get_r2_client
from vss_agents.utils.r2 import get_r2_presigned_url
from vss_agents.utils.r2 import is_r2_configured
from vss_agents.utils.r2 import reset_r2_client
from vss_agents.utils.r2 import resolve_r2_url

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _clear_r2_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    reset_r2_client()
    for var in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY",
        "R2_SECRET_KEY",
        "R2_BUCKET",
        "INCIDENT_VIDEO_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    reset_r2_client()


def test_is_r2_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not is_r2_configured()

    monkeypatch.setenv("R2_ACCOUNT_ID", "acc-123")
    monkeypatch.setenv("R2_ACCESS_KEY", "key-123")
    monkeypatch.setenv("R2_SECRET_KEY", "sec-123")
    assert not is_r2_configured()

    monkeypatch.setenv("R2_BUCKET", "my-bucket")
    assert is_r2_configured()


def test_get_r2_client_missing_credentials() -> None:
    with pytest.raises(ValueError, match="Cloudflare R2 credentials"):
        get_r2_client()


def test_get_r2_client_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc-123")
    monkeypatch.setenv("R2_ACCESS_KEY", "key-123")
    monkeypatch.setenv("R2_SECRET_KEY", "sec-123")

    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_boto.return_value = mock_client

        c1 = get_r2_client()
        c2 = get_r2_client()
        assert c1 is c2
        assert mock_boto.call_count == 1
        mock_boto.assert_called_once_with(
            "s3",
            endpoint_url="https://acc-123.r2.cloudflarestorage.com",
            aws_access_key_id="key-123",
            aws_secret_access_key="sec-123",
            region_name="auto",
            config=ANY,
        )


def test_get_r2_presigned_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc-123")
    monkeypatch.setenv("R2_ACCESS_KEY", "key-123")
    monkeypatch.setenv("R2_SECRET_KEY", "sec-123")
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = (
        "https://presigned.r2.cloudflarestorage.com/test-bucket/evidence/1.jpg"
    )

    with patch("boto3.client", return_value=mock_client):
        url = get_r2_presigned_url("evidence/1.jpg", expires_in=1800)
        assert url == "https://presigned.r2.cloudflarestorage.com/test-bucket/evidence/1.jpg"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "evidence/1.jpg", "ResponseContentDisposition": "inline"},
            ExpiresIn=1800,
        )


def test_resolve_r2_url_empty() -> None:
    assert resolve_r2_url("") == ""


def test_resolve_r2_url_existing_valid_http() -> None:
    valid_url = "https://cdn.example.org/videos/clip.mp4"
    assert resolve_r2_url(valid_url) == valid_url


def test_resolve_r2_url_strips_pub_r2_and_presigns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc-123")
    monkeypatch.setenv("R2_ACCESS_KEY", "key-123")
    monkeypatch.setenv("R2_SECRET_KEY", "sec-123")
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://signed.r2.com/evidence/crop.jpg"

    with patch("boto3.client", return_value=mock_client):
        dummy_url = "https://pub-r2.example.com/evidence/crop.jpg"
        resolved = resolve_r2_url(dummy_url)
        assert resolved == "https://signed.r2.com/evidence/crop.jpg"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "evidence/crop.jpg", "ResponseContentDisposition": "inline"},
            ExpiresIn=3600,
        )


def test_resolve_r2_url_public_base_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENT_VIDEO_BASE_URL", "https://pub-r2.mycdn.net")
    key = "evidence/Assault001/m1/instruments/I1.jpg"
    assert resolve_r2_url(key) == "https://pub-r2.mycdn.net/evidence/Assault001/m1/instruments/I1.jpg"


def test_resolve_r2_url_unconfigured_fallback() -> None:
    key = "evidence/Burglary/m2/entities/E1.jpg"
    assert resolve_r2_url(key) == key
