# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The final comparison's harness changes: per-run caption flags are not pinned, and its profile runs both stages."""

from evalv2.adapters.base import pinned_flags
from evalv2.requests.vss import PROFILES


def test_caption_outcome_flags_are_not_pinned():
    ran = {"chunking": {"setting_enabled": True, "window_s": 20, "enabled": True, "ran": True, "skipped": None}}
    short = {"chunking": {"setting_enabled": True, "window_s": 20, "enabled": False, "ran": False, "skipped": "short"}}
    assert pinned_flags(ran) == pinned_flags(short)


def test_final_profile_asks_for_captions_and_object_tracking():
    profile = PROFILES["final-v1-captions-object-tracking"]
    body = profile.body(video_url="u", model="m", duration_seconds=40.0)
    assert body["experiment_object_tracking"] is True and body["experiment_captions"] == "inline"
    assert {"caption", "object_tracking", "grounding", "zoom", "p1"} == set(profile.stages())
