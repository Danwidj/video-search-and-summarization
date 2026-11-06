# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for chat scorer correction v1; the frozen scorer's behaviour is pinned beside them."""

from types import SimpleNamespace

from evalv2.tasks.chat import scoring as sc
from evalv2.tasks.chat.corrections_v1 import exact_v1, window_seconds


def answer(text):
    return SimpleNamespace(text=text, refused=False)


LIST = {"kind": "list", "value": ["stick"]}


def test_plural_list_answer():
    a = answer("two long thin sticks")
    assert sc.exact(a, LIST, {"vocabulary": ["stick", "knife"]}) is False  # the frozen defect, unchanged
    assert exact_v1(a, LIST, {"vocabulary": ["stick", "knife"]}) is True


def test_extra_item_still_fails():
    assert exact_v1(answer("sticks and a knife"), LIST, {"vocabulary": ["stick", "knife"]}) is False


def test_window_reads_minutes_and_seconds():
    assert window_seconds("0:23 to 1:34") == [23, 94]
    window = {"kind": "window", "value": [23, 94]}
    assert sc.exact(answer("from 0:23 to 1:34"), window) is False  # the frozen defect, unchanged
    assert exact_v1(answer("from 0:23 to 1:34"), window) is True


def test_window_no_longer_passes_on_split_digits():
    window = {"kind": "window", "value": [0, 8]}
    assert sc.exact(answer("from 0:03 to 0:08"), window) is True  # the frozen defect, unchanged
    assert exact_v1(answer("from 0:03 to 0:08"), window) is False
