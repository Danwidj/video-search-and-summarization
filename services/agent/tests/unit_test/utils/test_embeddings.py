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

"""Unit tests for the remote text embedding client."""

import httpx
import pytest

from vss_agents.utils.embeddings import EMBEDDING_DIMENSIONS
from vss_agents.utils.embeddings import RemoteTextEmbedder


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _embedding_response(count: int, dims: int = EMBEDDING_DIMENSIONS) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"index": i, "embedding": [float(i)] * dims} for i in reversed(range(count))]},
    )


class TestRemoteTextEmbedder:
    @pytest.mark.asyncio
    async def test_embed_sends_input_type_and_dimensions_and_orders_by_index(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _embedding_response(2)

        embedder = RemoteTextEmbedder(
            base_url="https://embed.example/v1/",
            model="m",
            api_key="k",
            http_client=_client(httpx.MockTransport(handler)),
        )

        vectors = await embedder.embed(["a", "b"], input_type="passage")

        assert [v[0] for v in vectors] == [0.0, 1.0]
        assert str(seen[0].url) == "https://embed.example/v1/embeddings"
        assert seen[0].headers["Authorization"] == "Bearer k"
        body = seen[0].read().decode()
        assert '"input_type":"passage"' in body.replace(" ", "")
        assert '"dimensions":1024' in body.replace(" ", "")

    @pytest.mark.asyncio
    async def test_embed_query_returns_single_vector(self) -> None:
        embedder = RemoteTextEmbedder(
            api_key="k", http_client=_client(httpx.MockTransport(lambda _: _embedding_response(1)))
        )

        assert len(await embedder.embed_query("edged weapon")) == EMBEDDING_DIMENSIONS

    @pytest.mark.asyncio
    async def test_rejects_wrong_vector_size(self) -> None:
        embedder = RemoteTextEmbedder(
            api_key="k", http_client=_client(httpx.MockTransport(lambda _: _embedding_response(1, dims=2048)))
        )

        with pytest.raises(ValueError, match="expected 1 x 1024"):
            await embedder.embed_query("x")

    @pytest.mark.asyncio
    async def test_retries_transient_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def no_sleep(_: float) -> None:
            return None

        monkeypatch.setattr("vss_agents.utils.embeddings.asyncio.sleep", no_sleep)
        calls = {"n": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429) if calls["n"] == 1 else _embedding_response(1)

        embedder = RemoteTextEmbedder(api_key="k", http_client=_client(httpx.MockTransport(handler)))

        assert len(await embedder.embed_query("x")) == EMBEDDING_DIMENSIONS
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_requires_api_key(self) -> None:
        with pytest.raises(ValueError, match="API key is not configured"):
            await RemoteTextEmbedder(api_key="").embed_query("x")

    def test_api_key_falls_back_to_nvidia_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVIDENCE_EMBEDDING_API_KEY", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nv-key")

        assert RemoteTextEmbedder().api_key == "nv-key"
