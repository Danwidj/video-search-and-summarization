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

"""HTTP client for the platform's embedding endpoint.

Follows ``agent_client.py``'s pattern: every call fails soft, returning a
``Result`` with ``ok=False`` and a human-readable ``error`` rather than raising,
so ``matching.py`` degrades to "no matches computed" when the endpoint is
absent or misconfigured instead of crashing a page or a seed run.

``incident-console`` has its own ``pyproject.toml`` / venv and does not depend
on ``services/agent``'s ``vss_agents`` package, so this talks to the embedding
endpoint directly over HTTP rather than importing an embedding client from
there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

import config


@dataclass
class Result:
    ok: bool
    data: Any = None
    error: str = ""
    status_code: int | None = None


class EmbedClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        # ``None`` means "read from config"; an explicit "" stays empty.
        self.base_url = (config.embedding_base_url() if base_url is None else base_url).rstrip("/")
        self.timeout = timeout or config.http_timeout_seconds()

    def embed(self, texts: list[str], *, model: str = "embedding") -> Result:
        """OpenAI-compatible ``POST {base_url}/embeddings`` -> one vector per input text."""
        if not self.base_url:
            return Result(ok=False, error="INCIDENT_EMBEDDING_BASE_URL is not set")
        if not texts:
            return Result(ok=True, data=[])
        try:
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                json={"model": model, "input": texts},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return Result(ok=False, error=f"{type(exc).__name__}: {exc}")
        if resp.status_code >= 400:
            return Result(ok=False, status_code=resp.status_code, error=f"HTTP {resp.status_code}: {resp.text[:400]}")
        try:
            body = resp.json()
        except ValueError:
            return Result(ok=False, error="embedding endpoint returned a non-JSON body")
        try:
            vectors = [item["embedding"] for item in body["data"]]
        except (KeyError, TypeError, IndexError):
            return Result(ok=False, error=f"unexpected embedding response shape: {body!r}")
        return Result(ok=True, data=vectors, status_code=resp.status_code)


def embed_texts(texts: list[str], **kwargs: Any) -> Result:
    """Module-level convenience mirroring how ``agent_client`` is typically used."""
    return EmbedClient().embed(texts, **kwargs)
