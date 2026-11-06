# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Chat scorer correction v1 (diagnostic audit, 2026-11-05): separate from the frozen ``scoring.exact``, never replacing it.

- ``exact_v1``: list answers accept the references' own plural rule (a trailing -s or -es on the last word), and
  windows read m:ss times as seconds. The frozen scorer rejected "sticks" for "stick" and split "1:34" into 1 and 34.
Original and corrected figures are always reported side by side.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from evalv2.tasks.chat import scoring as sc

_MMSS = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def window_seconds(text: str | None) -> list[int]:
    """Every whole number in the text, with m:ss read as seconds first."""
    plain = _MMSS.sub(lambda m: f" {int(m.group(1)) * 60 + int(m.group(2))} ", text or "")
    return [int(w) for w in re.findall(r"\d+", plain)]


def _mentions_plural(text_words: Any, phrase: str) -> list[int]:
    target = list(sc.words(phrase))
    found: set[int] = set()
    for variant in (target, target[:-1] + [target[-1] + "s"] if target else [], target[:-1] + [target[-1] + "es"] if target else []):
        n = len(variant)
        found |= {i for i in range(len(text_words) - n + 1) if n and list(text_words[i:i + n]) == variant}
    return sorted(found)


def exact_v1(answer: Any, expected: Mapping[str, Any], space: Mapping[str, Any] | None = None, *,
             question_class: str | None = None) -> bool | None:
    """``scoring.exact`` with the two corrections."""
    if expected["kind"] == "window" and not answer.refused:
        value = expected.get("value")
        return value is not None and all(v in window_seconds(answer.text) for v in value)
    original = sc._mentions
    sc._mentions = _mentions_plural
    try:
        return sc.exact(answer, expected, space, question_class=question_class)
    finally:
        sc._mentions = original
