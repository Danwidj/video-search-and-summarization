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

"""Stage 1 readiness: judge caps derived from the ground truth, the full plan fits its caps, gateway timeouts, and
reliability / conditional / end-to-end reporting kept apart."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import experiment_report as rep  # noqa: E402
import experiment_runner as er  # noqa: E402
import extraction_stats  # noqa: E402
import pytest  # noqa: E402

STAGE1 = ("direct-vlm-baseline", "vss-baseline")
OUTCOME = SimpleNamespace(result=SimpleNamespace(raw={}))
PRICING = {"provisional": False, "source": "t", "usd_per_million_tokens": {"default": 0.0}, "judge_model": "j",
           "judge_tokens_per_call_estimate": 525}


def _gt(counts: dict[str, tuple[int, int, int]]):
    return {"status": "frozen", "version": "ground-truth-v1.0", "manifest": {"records_sha256": "g"},
            "split": {"version": "split-v2"},
            "by_incident_id": {v: {"category": "Assault", "filename": f"{v}.mp4", "p1_shaped": {
                "entities": [{}] * e, "instruments": [{}] * i, "assets": [{}] * a}} for v, (e, i, a) in counts.items()}}


COUNTS = {"V1": (2, 1, 3), "V2": (0, 0, 0), "V3": (5, 2, 1)}
SPLIT = {"version": "split-v2", "dev": sorted(COUNTS), "test": []}


def _config(**overrides):
    config = er.load_config(er.CONFIG_DIR / "direct-vlm-baseline.json")
    config.update({"experiment_id": "cap-check", "frozen_baseline": False, **overrides})
    return config


def test_judged_fields_follow_the_scorer():
    gt = _gt(COUNTS)["by_incident_id"]
    assert [er.judged_fields(gt[v]["p1_shaped"], "full") for v in sorted(COUNTS)] == [1 + 2 + 2 + 6, 1, 1 + 5 + 4 + 2]
    assert er.judged_fields(gt["V3"]["p1_shaped"], "incident_only") == 1


def test_the_required_cap_is_repeats_times_fields_times_attempts():
    caps = er.judge_cap_required(_config(), SPLIT, _gt(COUNTS))
    assert caps["judged_fields"] == 11 + 1 + 12
    assert caps["required"] == 2 * 24 * er.JUDGE_ATTEMPTS_PER_FIELD == 240


def test_committed_stage1_caps_equal_the_derivation_from_the_snapshot():
    snapshot = json.loads(er.JUDGE_CAPS_PATH.read_text())
    split = json.loads(er.SPLIT_PATH.read_text())
    assert snapshot["attempts_per_field"] == er.JUDGE_ATTEMPTS_PER_FIELD
    for row in snapshot["configs"]:
        config = er.load_config(er.CONFIG_DIR / f"{row['experiment_id']}.json")
        assert sorted(row["per_video"]) == sorted(er.videos_for(config, split))
        assert row["required"] == config["repeats"] * sum(row["per_video"].values()) * er.JUDGE_ATTEMPTS_PER_FIELD
        assert config["budget"]["max_judge_calls"] == row["required"], row["experiment_id"]
    assert {r["experiment_id"] for r in snapshot["configs"]} == set(STAGE1)


def _run(config, gt, tmp_path, *, tokens=9275, judge_worst=True, status="scored"):
    def run_one(store, *, incident_id, model_run_id, p1_call, **_):
        p1_call("m", "u")
        fields = er.judged_fields(gt["by_incident_id"][incident_id]["p1_shaped"], config["scoring"])
        return {"incident_id": incident_id, "outcome": status, "run_id": model_run_id,
                "judge_calls": fields * er.JUDGE_ATTEMPTS_PER_FIELD if judge_worst else fields, "judge_tokens": 0,
                "p1_raw": {"ok": True, "usage": {"total_tokens": tokens},
                           "rate_limit": {"attempt_count": 1, "attempts": [{"failure_kind": None}]}},
                "incident_field_scores": {}, "ground_truth": {}}

    class Store:
        def insert_model_run(self, *a, **k):
            pass

    return er.run_stage([config], split=SPLIT, gt_index=gt, store=Store(), video_source=lambda i: ("u", {}),
                        call_factory_for=lambda c: (lambda *a, **k: (lambda *b: OUTCOME)), run_one=run_one,
                        confirm_paid=True, results_root=tmp_path, now=datetime(2026, 11, 1, tzinfo=UTC),
                        log=lambda *_: None, pricing=PRICING)


def test_the_full_plan_at_worst_case_judge_usage_fits_the_derived_cap(tmp_path):
    gt = _gt(COUNTS)
    required = er.judge_cap_required(_config(), SPLIT, gt)["required"]
    config = _config(budget={"max_p1_calls": 6, "max_p1_tokens": 1_050_000, "max_judge_calls": required})
    out = _run(config, gt, tmp_path)
    assert out["stopped"] is None and out["records"][0]["complete"]
    assert out["records"][0]["usage"]["judge_calls"] == required  # every reserved attempt used, and still complete


def test_a_cap_one_below_the_derivation_is_refused_before_any_call(tmp_path):
    gt = _gt(COUNTS)
    required = er.judge_cap_required(_config(), SPLIT, gt)["required"]
    config = _config(budget={"max_p1_calls": 6, "max_p1_tokens": 1_050_000, "max_judge_calls": required - 1})
    with pytest.raises(er.ExperimentRefused, match="below the"):
        _run(config, gt, tmp_path)


def test_stage1_token_cap_fits_every_call_at_the_pilot_maximum(tmp_path):
    """50 calls at the pilot's largest call (16,232 tokens) still leave the 35,000-token reserve."""
    config = er.load_config(er.CONFIG_DIR / "direct-vlm-baseline.json")
    assert config["budget"]["max_p1_calls"] == er.planned_calls(config, json.loads(er.SPLIT_PATH.read_text())) == 50
    assert 49 * 16_232 + er.P1_TOKENS_CEILING <= config["budget"]["max_p1_tokens"]
    gt = _gt({f"V{i}": (1, 0, 1) for i in range(25)})
    split = {"version": "split-v2", "dev": sorted(gt["by_incident_id"]), "test": []}
    global SPLIT
    saved, SPLIT = SPLIT, split
    try:
        required = er.judge_cap_required(_config(), split, gt)["required"]
        small = _config(budget={**config["budget"], "max_judge_calls": required})
        out = _run(small, gt, tmp_path, tokens=16_232, judge_worst=False)
    finally:
        SPLIT = saved
    assert out["stopped"] is None and out["records"][0]["usage"]["p1_calls"] == 50


@pytest.mark.parametrize("status, body, kind", [
    (524, "<html>origin timeout</html>", "timeout"), (522, None, "timeout"), (504, {"detail": "x"}, "timeout"),
    (500, {"detail": "Analysis failed: P1 call returned HTTP 524: <!DOCTYPE html>"}, "timeout"),
    (500, {"detail": "Analysis failed: boom"}, "http_error"), (429, {}, "rate_limited"),
])
def test_gateway_timeouts_are_timeouts_in_the_vss_arm(status, body, kind):
    result = er.vss_chat_result(er.VSSResponse(status, body, 100.0), prompt_id="p1-v4-base", prompt_sha256="x",
                                started_at="s", finished_at="f")
    assert not result.ok and result.failure_kind == kind


def test_gateway_timeouts_are_timeouts_in_the_direct_arm(monkeypatch):
    import eval_vlm_client as client

    class Response:
        status_code = 524
        headers = {}
        text = "<html>timeout</html>"

        @staticmethod
        def json():
            raise ValueError("not json")

    monkeypatch.setattr(client, "gateway_credentials", lambda: ("http://gw.invalid/v1", "k"))
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: Response())
    result = client.chat_completion("m", [])
    assert not result.ok and result.failure_kind == "timeout" and result.status_code == 524


def _video(incident_id, outcome, passed=True):
    scores = {f: {"pass": passed} for f in extraction_stats.INCIDENT_FIELDS}
    return {"incident_id": incident_id, "outcome": outcome, "incident_field_scores": scores if outcome == "scored"
            else {f: {"pass": None} for f in extraction_stats.INCIDENT_FIELDS}, "ground_truth": {}}


def test_a_timed_out_clip_stays_in_reliability_and_end_to_end_but_not_conditional_accuracy():
    videos = [_video("A", "scored"), _video("B", "scored"), _video("C", "timeout")]
    rel = extraction_stats.reliability(videos)
    assert rel["attempted"] == 3 and rel["no_model_output"] == 1 and rel["outcomes"]["timeout"] == 1
    stats = extraction_stats.field_intervals(videos)["type"]
    assert stats["n"] == 2 and stats["accuracy"] == 1.0  # conditional: valid outputs only
    assert stats["no_model_output"] == 1
    assert stats["end_to_end"]["n"] == 3 and stats["end_to_end"]["accuracy"] == pytest.approx(2 / 3, abs=1e-4)  # a miss


def test_reports_show_reliability_conditional_and_end_to_end_separately():
    record = {"experiment_id": "x", "arm": "direct-vlm", "model": "m", "prompt": {"id": "p", "sha256": "s" * 64},
              "split": {"half": "dev"}, "plan": {"repeats": 1, "videos": 3}, "ground_truth": {"version": "v", "status": "frozen", "records_sha256": "g"},
              "harness_git_sha": "abc", "reportable": True, "purpose": "experiment", "complete": True,
              "videos": [_video("A", "scored"), _video("B", "scored"), _video("C", "timeout")]}
    text = rep.render({"baseline": record}, title="t")
    assert "## Reliability" in text and "End-to-end" in text and "Conditional accuracy" in text
    assert "'timeout': 1" in text
