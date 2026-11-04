# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 amendment A5: the split recovery configs and the contingency profile keep their stated invariants."""

from __future__ import annotations

import json
from pathlib import Path

from evalv2.core.config import load_config

A = Path(__file__).resolve().parents[2] / "experiments" / "v2" / "c3" / "amendments"


def _keys(name):
    return {(i.subject, i.item_id, i.repeat) for i in load_config(A / f"{name}.json").recovery.items}


def test_a5_split_is_disjoint_and_inside_the_a2_recovery():
    a2, a, s = _keys("c3-track-a-switchyard-recovery"), _keys("c3-track-a-switchyard-recovery-a5a"), \
        _keys("c3-track-a-switchyard-recovery-a5s")
    assert not a & s and a | s <= a2
    assert {k[0] for k in a} == {"nano-direct", "omni-direct"} and {k[0] for k in s} == {"super-direct"}
    assert len(a) == 170 and len(s) == 84


def test_a5_configs_change_only_the_subject_set():
    base = json.loads((A / "c3-track-a-switchyard-recovery.json").read_text())
    for name in ("c3-track-a-switchyard-recovery-a5a", "c3-track-a-switchyard-recovery-a5s"):
        c = json.loads((A / f"{name}.json").read_text())
        for key in ("split", "freeze_manifest", "purpose", "budget_mode", "seed", "retry_policy", "repeats", "tasks",
                    "datasets"):
            assert c[key] == base[key], (name, key)
        subjects = {s["id"]: s for s in base["subjects"]}
        assert all(s == subjects[s["id"]] for s in c["subjects"])


def test_contingency_is_nano_only_and_labelled():
    c = json.loads((A / "c3-track-b-contingency-nano-grounding.json").read_text())
    assert [s["model"] for s in c["subjects"]] == ["nvidia/cosmos-3-nano-reasoner"]
    assert c["experiment"] != "v2-c3-track-b-historical" and "NOT the pre-registered Track B" in c["notes"]
