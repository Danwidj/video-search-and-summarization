# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 amendments A2/A3: the recovery configs re-send only items without model output, never the crashed item."""

import json
from pathlib import Path

from evalv2.core.config import load_config

C3 = Path(__file__).resolve().parents[2] / "experiments" / "v2" / "c3"


def test_recovery_configs_are_final_test_runs_on_the_frozen_manifest():
    for name, base in (("c3-track-a-switchyard-recovery", "c3-track-a-switchyard"),
                       ("c3-track-b-historical-recovery", "c3-track-b-historical")):
        rec, orig = load_config(C3 / "amendments" / f"{name}.json"), load_config(C3 / f"{base}.json")
        assert rec.split.half == "test" and rec.purpose == "final" and rec.freeze_manifest == orig.freeze_manifest
        assert rec.recovery.of_experiment == orig.experiment
        assert [s.model for s in rec.subjects] == [s.model for s in orig.subjects]
        assert rec.tasks == orig.tasks and rec.repeats == orig.repeats


def test_the_crashed_item_is_never_re_sent():
    raw = json.loads((C3 / "amendments" / "c3-track-a-switchyard-recovery.json").read_text())
    keys = {(i["subject"], i["item_id"], i["repeat"]) for i in raw["recovery"]["items"]}
    assert ("omni-direct", "Explosion004", 1) not in keys and len(keys) == len(raw["recovery"]["items"])


def test_the_chat_amendment_changes_only_the_system_corpus_source():
    orig = json.loads((C3 / "c3-chat.json").read_text())
    a4 = json.loads((C3 / "amendments" / "c3-chat-a4.json").read_text())
    so, sa = orig["tasks"]["chat"]["options"], a4["tasks"]["chat"]["options"]
    assert {k: v for k, v in so.items() if k != "system"} == {k: v for k, v in sa.items() if k != "system"}
    assert sa["system"]["run"] == "v2-c3-track-b-historical-recovery" and sa["system"]["subject"] == so["system"]["subject"]
    assert a4["caps"] == orig["caps"] and a4["freeze_manifest"] == orig["freeze_manifest"]
