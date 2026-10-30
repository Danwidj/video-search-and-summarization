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

"""Cloudflare R2 storage helpers for signing and generating accessible URLs.

Provides helpers for building presigned or public Cloudflare R2 URLs for video
files and evidence crops, mirroring deploy/docker/developer-profiles/dev-profile-incident/archived/incident-console/r2_videos.py (archived v1).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_r2_client: Any = None


def get_r2_key_prefix() -> str:
    """Return the R2 key prefix from ``R2_KEY_PREFIX`` (empty string when unset).

    The prefix is normalised: no leading slash, exactly one trailing slash when
    non-empty.  DB keys are stored without the prefix; the prefix is applied
    only at the R2 boundary so every read, write, list and sign lands under it.
    """
    raw = (os.getenv("R2_KEY_PREFIX") or "").strip().strip("/")
    return f"{raw}/" if raw else ""


def is_r2_configured() -> bool:
    """Return True if Cloudflare R2 credentials and bucket are configured."""
    return all(
        bool((os.getenv(k) or "").strip()) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET")
    )


def get_r2_client() -> Any:
    """Return a cached boto3 S3 client configured for Cloudflare R2."""
    global _r2_client
    if _r2_client is not None:
        return _r2_client

    import boto3
    from botocore.config import Config

    account_id = (os.getenv("R2_ACCOUNT_ID") or "").strip()
    access_key = (os.getenv("R2_ACCESS_KEY") or "").strip()
    secret_key = (os.getenv("R2_SECRET_KEY") or "").strip()

    if not (account_id and access_key and secret_key):
        raise ValueError("Cloudflare R2 credentials (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY) are not set")

    _r2_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=20,
            retries={"max_attempts": 2},
        ),
    )
    return _r2_client


def reset_r2_client() -> None:
    """Reset the cached R2 client (used in tests)."""
    global _r2_client
    _r2_client = None


def get_r2_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for an object in the configured R2 bucket.

    ``key`` is the logical (prefix-free) DB key.  The ``R2_KEY_PREFIX`` is
    prepended before the request so the signed URL points to the real object.
    """
    bucket = (os.getenv("R2_BUCKET") or "").strip()
    if not bucket:
        raise ValueError("R2_BUCKET environment variable is not set")
    client = get_r2_client()
    clean_key = get_r2_key_prefix() + key.lstrip("/")
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": clean_key, "ResponseContentDisposition": "inline"},
            ExpiresIn=expires_in,
        )
    )


def resolve_r2_url(key_or_url: str, expires_in: int = 3600) -> str:
    """Resolve a storage key or URL into an accessible URL for consumers (e.g. Brev critic).

    - If the input points to a dummy mock domain ('pub-r2.example.com'), strips the
      mock host to extract the underlying object key.
    - If the input is already a valid non-dummy http/https URL, returns it directly.
    - If a public base URL is configured via INCIDENT_VIDEO_BASE_URL,
      returns the public URL.
    - If Cloudflare R2 credentials are configured, generates a presigned R2 URL.
    - Otherwise returns the key or original URL as fallback.
    """
    if not key_or_url:
        return ""

    ref = key_or_url.strip()

    # Strip dummy host if present from sample/legacy data
    if "pub-r2.example.com/" in ref:
        ref = ref.split("pub-r2.example.com/", 1)[1]

    # If it is already a full URL that is not the dummy host
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref

    clean_key = ref.lstrip("/")

    # Check for public base URL (prefix applied so the URL reaches the real object)
    public_base = (os.getenv("INCIDENT_VIDEO_BASE_URL") or "").strip()
    if public_base:
        prefixed_key = get_r2_key_prefix() + clean_key
        return f"{public_base.rstrip('/')}/{prefixed_key}"

    # Generate presigned URL if R2 credentials exist (prefix handled inside get_r2_presigned_url)
    if is_r2_configured():
        try:
            return get_r2_presigned_url(clean_key, expires_in=expires_in)
        except Exception as exc:
            logger.warning("Failed to generate R2 presigned URL for key '%s': %s", clean_key, exc)

    return key_or_url
