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

"""``extract_json``'s fenced/bare-JSON fallback chain - no live network calls."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_vlm_client import FIXED_INFERENCE_CONFIG, extract_json  # noqa: E402


def test_extract_json_plain_object():
    assert extract_json('{"incident": {"type": "burglary"}}') == {"incident": {"type": "burglary"}}


def test_extract_json_fenced_code_block():
    text = '```json\n{"incident": {"type": "assault"}}\n```'
    assert extract_json(text) == {"incident": {"type": "assault"}}


def test_extract_json_bare_object_with_surrounding_text():
    text = 'Sure, here is the result:\n{"incident": {"type": "explosion"}}\nHope this helps.'
    assert extract_json(text) == {"incident": {"type": "explosion"}}


def test_extract_json_none_input_returns_none():
    assert extract_json(None) is None


def test_extract_json_unparseable_returns_none():
    assert extract_json("not json at all, sorry") is None


def test_fixed_inference_config_is_the_only_variable_across_models():
    # A guard against accidental per-model drift: this dict must never be
    # mutated per model/category/video by any caller - it's read, not built.
    assert FIXED_INFERENCE_CONFIG == {"temperature": 0.0, "max_tokens": 4096}
