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

"""Text-exemplar few-shot block builder - the final, confirmed calibration
mechanism (see the plan's Step 3: multi-turn video and frame-based visual
few-shot were both tested and ruled out for at least one of the three
models; text-exemplar is the one mechanism that works identically for all
three).

Deterministic serialization: examples are pretty-printed JSON, in the exact
order given (the split manifest's ``few_shot_demo_videos`` list, itself
alphabetically sorted - not re-sorted or shuffled here), identical for every
model and every held-out video in a category. GT for the held-out video being
evaluated is never included here - only the category's fixed 5 demonstration
examples are, and the caller is responsible for never passing anything else
in.
"""

from __future__ import annotations

import json

_HEADER = (
    "Before analysing the video below, here are {n} worked examples for this "
    "incident category, each showing a video's correct structured JSON output "
    "in the exact schema you must use. These examples are for reference only - "
    "they are not the video you are being asked to analyse."
)


def build_few_shot_block(examples: list[dict]) -> str:
    """``examples``: P1-shaped GT dicts (``{"incident": ..., "entities": ..., ...}``),
    in the exact order to present them - typically a category's 5 few-shot
    demonstration videos, sorted by filename by the split manifest.
    """
    if not examples:
        return ""
    parts = [_HEADER.format(n=len(examples))]
    for i, example in enumerate(examples, start=1):
        parts.append(f"\nEXAMPLE {i}:\n{json.dumps(example, indent=2)}")
    parts.append(
        "\nNow analyse the ACTUAL VIDEO below (not any example above) and "
        "produce structured JSON in the exact same format, for this video only."
    )
    return "\n".join(parts)
