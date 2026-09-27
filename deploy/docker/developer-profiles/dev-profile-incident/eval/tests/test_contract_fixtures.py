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

"""Cross-language guards for the shared contract (test-only; eval behaviour is unchanged).

``contracts/fixtures/`` is validated by both this suite and incident-console-v2's
``tests/contract-validate.test.mjs``, so the Python and TypeScript validators must
agree on every fixture. ``contracts/inference.json`` is the console's copy of the
P1 settings and model list; it must stay equal to eval's own constants.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import contract  # noqa: E402
import eval_vlm_client  # noqa: E402

FIXTURES = contract.CONTRACTS_DIR / "fixtures"
INFERENCE = json.loads((contract.CONTRACTS_DIR / "inference.json").read_text())


def _fixtures(kind: str) -> list[Path]:
    return sorted((FIXTURES / kind).glob("*.json"))


def test_fixture_directories_are_populated():
    assert _fixtures("valid") and _fixtures("invalid")


@pytest.mark.parametrize("path", _fixtures("valid"), ids=lambda p: p.stem)
def test_valid_fixture_passes(path: Path):
    contract.validate_report(json.loads(path.read_text()))


@pytest.mark.parametrize("path", _fixtures("invalid"), ids=lambda p: p.stem)
def test_invalid_fixture_is_rejected(path: Path):
    with pytest.raises(contract.ContractError):
        contract.validate_report(json.loads(path.read_text()))


def test_response_format_fixture_matches_python():
    assert json.loads((FIXTURES / "response_format.json").read_text()) == contract.response_format()


def test_inference_json_models_match_eval():
    assert [model["id"] for model in INFERENCE["models"]] == eval_vlm_client.MODELS


def test_inference_json_p1_settings_match_eval():
    eval_p1 = {**eval_vlm_client.FIXED_INFERENCE_CONFIG, **eval_vlm_client.P1_INFERENCE_CONFIG}
    assert INFERENCE["p1"] == eval_p1
