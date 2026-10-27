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

"""Experiment reports, reproducibility checks, budgets and the selection guard (PR 7). Offline only."""

from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import experiment_report as rep
import experiment_runner as er
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_experiment_plumbing  # noqa: E402
from test_ground_truth_freeze import _write  # noqa: E402

SPLIT = {"version": "split-v2", "dev": ["Assault001", "Burglary002"], "test": [],
         "by_category": {"Assault": {"dev": ["Assault001"], "test": []},
                         "Burglary": {"dev": ["Burglary002"], "test": []}}}


@pytest.fixture(scope="module")
def plumbing(tmp_path_factory):
    root = tmp_path_factory.mktemp("plumbing")
    gt = _write(root / "gt", status="candidate")
    return eval_experiment_plumbing.plumbing_run(root / "results", gt_dir=gt, split=SPLIT,
                                                 now=datetime(2026, 11, 1, tzinfo=UTC)), root


def test_the_offline_plumbing_run_covers_c1_to_c4_end_to_end(plumbing):
    result, _ = plumbing
    assert set(result["records"]) == {"C1", "C2", "C3", "C4"}
    assert all(not problems for problems in result["verify"].values())
    assert result["comparisons"]["problems"] == []
    assert all(not r["reportable"] for r in result["records"].values())
    vss = result["records"]["C2"]["videos"][0]["transport"]
    assert vss["p1_elapsed_ms"] == 10000.0 and vss["end_to_end_s"] == 12.5


def test_a_report_on_candidate_ground_truth_is_marked_not_reportable(plumbing):
    result, _ = plumbing
    text = result["report"].read_text()
    assert "NOT REPORTABLE" in text.split("## Configurations")[0]
    for section in ("## Incident fields", "## Severity", "## Reliability", "## Inference latency",
                    "## End-to-end latency", "## Paired comparisons", "## Interpretation limits", "## Held-out exposure"):
        assert section in text
    assert "C3-C1" in text and "never an architectural extraction advantage" in text


def test_a_reportable_set_has_no_banner(plumbing):
    records = copy.deepcopy(plumbing[0]["records"])
    for record in records.values():
        record["reportable"] = True
    assert "NOT REPORTABLE" not in rep.render(records, title="t")


def test_latency_keeps_inference_and_end_to_end_apart(plumbing):
    records = plumbing[0]["records"]
    direct, vss = rep.latency(records["C1"]), rep.latency(records["C2"])
    assert direct["inference"]["p50"] == 10.0 and direct["end_to_end"]["n"] == 0
    assert vss["inference"]["p50"] == 10.0 and vss["end_to_end"]["p50"] == 12.5


def test_verify_detects_an_edited_result(plumbing, tmp_path):
    _, root = plumbing
    source = next((root / "results" / "plumbing-c1").iterdir())
    copied = tmp_path / "run"
    copied.mkdir()
    for name in ("results.json", "prompt.txt", "results.sha256"):
        (copied / name).write_bytes((source / name).read_bytes())
    assert rep.verify(copied, split=SPLIT) == []
    record = json.loads((copied / "results.json").read_text())
    record["videos"][0]["outcome"] = "edited"
    (copied / "results.json").write_text(json.dumps(record))
    assert any("results.sha256" in p for p in rep.verify(copied, split=SPLIT))
    (copied / "prompt.txt").write_text("another prompt")
    assert any("prompt.txt" in p for p in rep.verify(copied, split=SPLIT))
    assert any("ground truth" in p for p in rep.verify(copied, split=SPLIT, gt_manifest={"records_sha256": "x"}))


def test_budget_counts_calls_and_prices_only_measured_pilots():
    split = json.loads(er.SPLIT_PATH.read_text())
    configs = [er.load_config(p) for p in sorted(er.CONFIG_DIR.glob("*.json"))]
    statement = rep.budget(configs, split)
    rows = {r["experiment_id"]: r for r in statement["rows"]}
    assert rows["direct-vlm-baseline"]["p1_calls"] == 50 and rows["pilot-direct-vlm"]["p1_calls"] == 5
    assert rows["pilot-vss"]["crop_calls"] == 0 and rows["pilot-vss"]["purpose"] == "pilot"
    assert statement["basis"].startswith("planning") and "pricing_source" in statement
    assert rows["pilot-direct-vlm"]["p1_tokens_estimate"] == 5 * er.P1_TOKENS_PLANNING_MEAN
    measured = rep.budget(configs[:1], split, measured={"tokens_per_p1_call": 1000, "judge_calls_per_video": 2})
    assert measured["basis"] == "pilot measurements" and measured["rows"][0]["judge_calls_estimate"] == \
        2 * er.planned_calls(configs[0], split)


def _dev(record, score):
    out = copy.deepcopy(record)
    out["reportable"] = True
    out["_score"] = score
    return out


def test_selection_needs_a_pre_registered_rule_and_dev_results_only(plumbing, tmp_path):
    record = plumbing[0]["records"]["C2"]
    decisions = tmp_path / "decisions.md"
    decisions.write_text("# log\n\n### 2026-11-01: Stage 2 selection rule pre-registered\n")
    rule = lambda candidate, baseline: candidate["_score"]  # noqa: E731
    candidates = {"e01": _dev(record, 0.4), "e02": _dev(record, 0.6)}
    chosen = rep.select(candidates, _dev(record, 0), rule_record="2026-11-01: Stage 2 selection rule pre-registered",
                        rule=rule, decisions_path=decisions)
    assert chosen["selected"] == "e02"
    with pytest.raises(rep.SelectionRefused, match="not pre-registered"):
        rep.select(candidates, _dev(record, 0), rule_record="2026-11-02: other", rule=rule, decisions_path=decisions)
    test_record = _dev(record, 0.9)
    test_record["split"]["half"] = "test"
    with pytest.raises(rep.SelectionRefused, match="dev results only"):
        rep.select({**candidates, "e03": test_record}, _dev(record, 0),
                   rule_record="2026-11-01: Stage 2 selection rule pre-registered", rule=rule, decisions_path=decisions)
    with pytest.raises(rep.SelectionRefused, match="not reportable"):
        rep.select({"e01": record}, _dev(record, 0), rule_record="2026-11-01: Stage 2 selection rule pre-registered",
                   rule=rule, decisions_path=decisions)


def test_a_pilot_subset_must_lie_inside_its_split_half():
    config = er.load_config(er.CONFIG_DIR / "pilot-direct-vlm.json")
    split = json.loads(er.SPLIT_PATH.read_text())
    assert er.videos_for(config, split) == sorted(config["videos"])
    assert len({v.rstrip("0123456789") for v in config["videos"]}) == 5  # one per category
    with pytest.raises(er.ExperimentRefused, match="not in the dev half"):
        er.videos_for({**config, "videos": [split["test"][0]]}, split)
