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

"""Gated experimental settings for ``/analyze`` (dev-profile-incident prompt experiments, PR 6B).

Production never reaches this module's prompts: an experimental request (one that sets
``experiment_prompt_id`` or ``skip_crops``) is refused unless the operator started the agent
with ``INCIDENT_EXPERIMENTS_ENABLED=1``. The prompts come from the append-only registry
``dev-profile-incident/contracts/experiments/registry.json`` in the checkout (or
``INCIDENT_EXPERIMENT_REGISTRY``); they are never vendored. A prompt is served only when its
file matches the SHA-256 recorded in the registry and its contract version is the vendored one.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from vss_agents import incident_contract

EXPERIMENTS_FLAG = "INCIDENT_EXPERIMENTS_ENABLED"
REGISTRY_ENV = "INCIDENT_EXPERIMENT_REGISTRY"
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[5]  # the repository root, from services/agent/src/vss_agents/tools/
    / "deploy"
    / "docker"
    / "developer-profiles"
    / "dev-profile-incident"
    / "contracts"
    / "experiments"
    / "registry.json"
)
PROMPT_ID_PATTERN = re.compile(r"^p1-v\d+-(base|e\d{2}[a-z0-9-]*)$")


class ExperimentsDisabledError(PermissionError):
    """An experimental setting was requested but the agent was not started with experiments enabled."""


class ExperimentPromptError(ValueError):
    """The requested experiment prompt is unknown, edited, or for another contract version."""


def experiments_enabled() -> bool:
    return os.environ.get(EXPERIMENTS_FLAG, "") == "1"


def registry_path() -> Path:
    return Path(os.environ.get(REGISTRY_ENV) or DEFAULT_REGISTRY)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def production_prompt_sha256() -> str:
    return sha256_text(incident_contract.extraction_prompt())


def require_enabled() -> None:
    if not experiments_enabled():
        raise ExperimentsDisabledError(
            f"experimental settings are disabled on this agent (start it with {EXPERIMENTS_FLAG}=1)"
        )


def resolve_prompt(prompt_id: str) -> tuple[str, str]:
    """``(text, sha256)`` of a registry prompt, verified; raises ``ExperimentPromptError``."""
    require_enabled()
    if not PROMPT_ID_PATTERN.match(prompt_id):
        raise ExperimentPromptError(f"{prompt_id!r} is not a registry prompt id")
    path = registry_path()
    try:
        registry: dict[str, Any] = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ExperimentPromptError(f"cannot read the experiment prompt registry at {path}: {exc}") from exc
    entry = next((item for item in registry.get("prompts", []) if item.get("id") == prompt_id), None)
    if entry is None:
        raise ExperimentPromptError(f"{prompt_id!r} is not in the experiment prompt registry")
    if entry.get("contract_version") != incident_contract.contract_version():
        raise ExperimentPromptError(
            f"{prompt_id!r} is for {entry.get('contract_version')!r}, not {incident_contract.contract_version()!r}"
        )
    data = (path.parent / entry["file"]).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.get("sha256"):
        raise ExperimentPromptError(f"{entry['file']} does not match its registered SHA-256")
    return data.decode(), digest
