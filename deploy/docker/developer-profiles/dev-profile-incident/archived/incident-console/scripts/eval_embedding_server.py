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

"""Real, local OpenAI-compatible ``/v1/embeddings`` server, for when no remote
embedding endpoint is reachable (this sandbox: confirmed no ``INCIDENT_EMBEDDING
_BASE_URL`` configured, and the only reachable inference gateway - ``vlm-gateway``
/ the switchyard - has no ``/v1/embeddings`` route at all, confirmed via a live
404).

Deliberately **not** a stub: uses a real pretrained sentence-embedding model
(``sentence-transformers/all-MiniLM-L6-v2``) to produce genuine semantic
vectors, so ``matching.py``'s cosine-similarity + Hungarian assignment gets
real signal - not ``mock_llm_server.py``'s deterministic hashed-bag-of-words
stub, which would silently produce non-semantic "matches."

``embed_client.py`` and ``matching.py`` are untouched: this only changes where
``INCIDENT_EMBEDDING_BASE_URL`` points, over the exact same OpenAI-compatible
contract they already speak (unauthenticated, matching the existing local-dev
pattern - this only ever binds to localhost, never in a way that would treat
this as a real remote credentialed service).

Usage::

    .venv/bin/python3 scripts/eval_embedding_server.py --port 8811
"""

from __future__ import annotations

import argparse

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

app = FastAPI(title="Local real embeddings for the P1/RP1 eval")
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


class EmbeddingsRequest(BaseModel):
    model: str = "embedding"
    input: list[str]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/v1/embeddings")
def embeddings(req: EmbeddingsRequest) -> dict:
    model = _get_model()
    vectors = model.encode(req.input, normalize_embeddings=False).tolist()
    return {
        "object": "list",
        "model": MODEL_NAME,
        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
    }


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"Loading {MODEL_NAME} ...")
    _get_model()
    print(f"Ready. Set INCIDENT_EMBEDDING_BASE_URL=http://{args.host}:{args.port}/v1")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
