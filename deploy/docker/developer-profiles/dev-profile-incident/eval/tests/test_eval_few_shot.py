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

"""Text-exemplar few-shot block: deterministic order, no held-out GT leakage."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_few_shot import build_few_shot_block  # noqa: E402


def test_build_few_shot_block_empty_examples_is_empty_string():
    assert build_few_shot_block([]) == ""


def test_build_few_shot_block_preserves_given_order():
    examples = [
        {"incident": {"type": "burglary"}, "entities": [], "instruments": [], "assets": []},
        {"incident": {"type": "assault"}, "entities": [], "instruments": [], "assets": []},
    ]
    block = build_few_shot_block(examples)
    assert block.index('"burglary"') < block.index('"assault"')
    assert "EXAMPLE 1:" in block and "EXAMPLE 2:" in block
    assert block.index("EXAMPLE 1:") < block.index("EXAMPLE 2:")


def test_build_few_shot_block_mentions_count_and_final_instruction():
    examples = [{"incident": {"type": "explosion"}, "entities": [], "instruments": [], "assets": []}]
    block = build_few_shot_block(examples)
    assert "1 worked examples" in block
    assert "ACTUAL VIDEO below" in block


def test_build_few_shot_block_is_identical_across_calls_same_input():
    examples = [{"incident": {"type": "animal attack"}, "entities": [], "instruments": [], "assets": []}]
    assert build_few_shot_block(examples) == build_few_shot_block(examples)
