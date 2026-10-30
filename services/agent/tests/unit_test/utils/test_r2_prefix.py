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

"""Tests for R2_KEY_PREFIX behaviour in r2.py and crop_evidence.py."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.utils.crop_evidence import R2EvidenceStore
from vss_agents.utils.r2 import get_r2_key_prefix
from vss_agents.utils.r2 import get_r2_presigned_url
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
        "R2_KEY_PREFIX",
        "INCIDENT_VIDEO_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    reset_r2_client()


# ---------------------------------------------------------------------------
# get_r2_key_prefix
# ---------------------------------------------------------------------------


def test_prefix_empty_when_unset() -> None:
    assert get_r2_key_prefix() == ""


def test_prefix_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_KEY_PREFIX", "mvp3")
    assert get_r2_key_prefix() == "mvp3/"


def test_prefix_strips_slashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_KEY_PREFIX", "/mvp3/")
    assert get_r2_key_prefix() == "mvp3/"


def test_prefix_empty_string_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_KEY_PREFIX", "")
    assert get_r2_key_prefix() == ""


# ---------------------------------------------------------------------------
# get_r2_presigned_url with prefix
# ---------------------------------------------------------------------------


def _r2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY", "key")
    monkeypatch.setenv("R2_SECRET_KEY", "sec")
    monkeypatch.setenv("R2_BUCKET", "bucket")


def test_presigned_url_no_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _r2_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://signed/evidence/v.mp4/run-1/E1.jpg"
    with patch("boto3.client", return_value=mock_client):
        get_r2_presigned_url("evidence/v.mp4/run-1/E1.jpg")
    mock_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "bucket", "Key": "evidence/v.mp4/run-1/E1.jpg", "ResponseContentDisposition": "inline"},
        ExpiresIn=3600,
    )


def test_presigned_url_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _r2_env(monkeypatch)
    monkeypatch.setenv("R2_KEY_PREFIX", "mvp3")
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://signed/mvp3/evidence/v.mp4/run-1/E1.jpg"
    with patch("boto3.client", return_value=mock_client):
        get_r2_presigned_url("evidence/v.mp4/run-1/E1.jpg")
    mock_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "bucket", "Key": "mvp3/evidence/v.mp4/run-1/E1.jpg", "ResponseContentDisposition": "inline"},
        ExpiresIn=3600,
    )


# ---------------------------------------------------------------------------
# resolve_r2_url with prefix
# ---------------------------------------------------------------------------


def test_resolve_public_base_no_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENT_VIDEO_BASE_URL", "https://cdn.example.com")
    assert resolve_r2_url("evidence/clip.mp4/run-1/E1.jpg") == "https://cdn.example.com/evidence/clip.mp4/run-1/E1.jpg"


def test_resolve_public_base_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENT_VIDEO_BASE_URL", "https://cdn.example.com")
    monkeypatch.setenv("R2_KEY_PREFIX", "mvp3")
    assert (
        resolve_r2_url("evidence/clip.mp4/run-1/E1.jpg")
        == "https://cdn.example.com/mvp3/evidence/clip.mp4/run-1/E1.jpg"
    )


def test_resolve_presigned_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _r2_env(monkeypatch)
    monkeypatch.setenv("R2_KEY_PREFIX", "mvp3")
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://signed/mvp3/evidence/clip.mp4/run-1/E1.jpg"
    with patch("boto3.client", return_value=mock_client):
        url = resolve_r2_url("evidence/clip.mp4/run-1/E1.jpg")
    assert url == "https://signed/mvp3/evidence/clip.mp4/run-1/E1.jpg"
    _, call_kwargs = mock_client.generate_presigned_url.call_args
    assert call_kwargs["Params"]["Key"] == "mvp3/evidence/clip.mp4/run-1/E1.jpg"


# ---------------------------------------------------------------------------
# R2EvidenceStore prefix
# ---------------------------------------------------------------------------


def _make_store(prefix: str | None, monkeypatch: pytest.MonkeyPatch) -> R2EvidenceStore:
    if prefix is not None:
        monkeypatch.setenv("R2_KEY_PREFIX", prefix)
    mock_client = MagicMock()
    return R2EvidenceStore(bucket="bucket", client=mock_client), mock_client  # type: ignore[return-value]


def test_put_image_no_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    store, mock_client = _make_store(None, monkeypatch)
    asyncio.run(store.put_image("evidence/v.mp4/run-1/E1.jpg", b"bytes"))
    mock_client.put_object.assert_called_once()
    assert mock_client.put_object.call_args.kwargs["Key"] == "evidence/v.mp4/run-1/E1.jpg"


def test_put_image_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    store, mock_client = _make_store("mvp3", monkeypatch)
    returned_key = asyncio.run(store.put_image("evidence/v.mp4/run-1/E1.jpg", b"bytes"))
    mock_client.put_object.assert_called_once()
    # R2 receives the prefixed key
    assert mock_client.put_object.call_args.kwargs["Key"] == "mvp3/evidence/v.mp4/run-1/E1.jpg"
    # Caller gets back the prefix-free key (what goes in the DB)
    assert returned_key == "evidence/v.mp4/run-1/E1.jpg"


def test_put_image_cannot_reach_outside_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key constructed outside the prefix folder is rejected by the store because the prefix
    is always prepended; the R2 key always starts with the prefix."""
    store, mock_client = _make_store("mvp3", monkeypatch)
    asyncio.run(store.put_image("other/v.mp4/run-1/E1.jpg", b"bytes"))
    actual_key = mock_client.put_object.call_args.kwargs["Key"]
    assert actual_key.startswith("mvp3/"), f"Expected prefixed key, got {actual_key!r}"


def test_get_image_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    store, mock_client = _make_store("mvp3", monkeypatch)
    mock_client.get_object.return_value = {"Body": MagicMock(read=lambda: b"img")}
    asyncio.run(store.get_image("evidence/v.mp4/run-1/E1.jpg"))
    assert mock_client.get_object.call_args.kwargs["Key"] == "mvp3/evidence/v.mp4/run-1/E1.jpg"


def test_next_batch_id_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    store, mock_client = _make_store("mvp3", monkeypatch)

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"CommonPrefixes": [{"Prefix": "mvp3/evidence/v.mp4/run-1/"}, {"Prefix": "mvp3/evidence/v.mp4/run-2/"}]}
    ]
    mock_client.get_paginator.return_value = paginator

    batch_id = asyncio.run(store.next_batch_id("v.mp4"))
    assert batch_id == "run-3"
    paginator.paginate.assert_called_once_with(Bucket="bucket", Prefix="mvp3/evidence/v.mp4/", Delimiter="/")


def test_next_batch_id_no_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    store, mock_client = _make_store(None, monkeypatch)

    paginator = MagicMock()
    paginator.paginate.return_value = [{"CommonPrefixes": [{"Prefix": "evidence/v.mp4/run-1/"}]}]
    mock_client.get_paginator.return_value = paginator

    batch_id = asyncio.run(store.next_batch_id("v.mp4"))
    assert batch_id == "run-2"
    paginator.paginate.assert_called_once_with(Bucket="bucket", Prefix="evidence/v.mp4/", Delimiter="/")
