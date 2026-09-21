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

# VLM Gateway

Thin proxy service for NVIDIA-hosted OpenAI-compatible LLM/VLM inference.

## Purpose

Holds the single real API credential server-side so that browser-facing consumers
(e.g., the future `incident-console-v2` Next.js app) can call LLM/VLM inference
without exposing the key client-side. Both `incident-console` (Streamlit) and
`incident-console-v2` will call this gateway.

## Contract

- **One route**: `POST /v1/chat/completions` (OpenAI chat completions compatible)
- **Authentication**: Gateway adds `Authorization: Bearer <VLM_GATEWAY_API_KEY>` header server-side
- **Upstream**: Configured via `VLM_GATEWAY_BASE_URL` (default: `https://switchyard-13doh4lsz.brevlab.com/v1`)
- **Model selection**: Caller specifies model in request body's `model` field; gateway is model-agnostic
- **No streaming** in this first version (returns full response verbatim)

## Available Models (upstream)

### Text Models
- `nvidia/nemotron-3-nano-30b-a3b`
- `nvidia/nemotron-3-super-120b-a12b`
- `nvidia/nemotron-3-ultra`
- `nvidia/nemotron-3-ultra-nvfp4`
- `nvidia/nemotron-3.5-lightning-30b-a3b`
- `nvidia/nemotron-3-auto` (auto-routing)

### Vision-Language Models (VLM)
- `nvidia/cosmos-3-nano-reasoner`
- `nvidia/cosmos-3-super-reasoner`
- `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`
- `nvidia/cosmos-3-auto` (auto-routing)

## Local Development

```bash
# From this directory
uv sync
uv run uvicorn app:app --port 8600
```

The gateway will be available at `http://localhost:8600/v1/chat/completions`.

### Environment Setup

Local developer secrets across all services in this profile are consolidated into
the shared root file at `dev-profile-incident/.env.local`. In this directory,
`.env.local` is a symlink pointing to `../.env.local`:

```bash
# If .env.local symlink is missing:
ln -s ../.env.local .env.local

# Ensure VLM_GATEWAY_API_KEY is set in dev-profile-incident/.env.local (captain provides)
```

## Example Usage

```bash
curl -X POST http://localhost:8600/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/nemotron-3-auto",
    "messages": [
      {"role": "user", "content": "Describe this incident in one sentence."}
    ]
  }'
```

## VM Deployment

Deployed as part of the `dev-profile-incident` stack via `docker compose --profile bp_developer_search_2d up -d vlm-gateway`.

The real `VLM_GATEWAY_API_KEY` is injected at deploy time via `generated.env.remote` (never committed).

Container name: `vss-vlm-gateway`
Port: `8600` (host networking)