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

"""D10 interleaving and order, D11 hard caps and cost logging, pilot isolation, and the D9 v2 selection metric."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import experiment_report as rep  # noqa: E402
import experiment_runner as er  # noqa: E402
import experiment_selection as sel  # noqa: E402
import pytest  # noqa: E402

OUTCOME = SimpleNamespace(result=SimpleNamespace(raw={}))
PRICING = {"provisional": True, "source": "test", "usd_per_million_tokens": {"default": 10.0},
           "judge_model": "judge", "judge_tokens_per_call_estimate": 1000}
SPLIT = {"version": "split-v2", "dev": ["A1", "A2", "A3", "A4"], "test": []}


def _config(name, **overrides):
    config = {"experiment_id": name, "description": "", "arm": "direct-vlm", "prompt_id": "p1-v4-base",
              "model": "nvidia/cosmos-3-super-reasoner", "split": "dev",
              "ground_truth": {"dir": "gt", "allow_candidate": True}, "repeats": 2,
              "budget": {"max_p1_calls": 8, "max_p1_tokens": 8 * er.P1_TOKENS_CEILING, "max_judge_calls": 80},
              "pipeline": {"profile": "accuracy", "skip_rp1": True, "skip_crops": True, "agent_base_url": None},
              "frozen_baseline": False, "final": False, "selection_record": None, "baseline_ref": None,
              "videos": None, "purpose": "experiment", "scoring": "full"}
    config.update(overrides)
    return config


class FakeStore:
    def insert_model_run(self, *args, **kwargs):
        pass


def _fake_run_one(tokens=9000, judge=3, rate_limited=0, outcome="scored"):
    def run_one(store, *, incident_id, model_run_id, p1_call, **_):
        p1_call("m", "u")
        return {"incident_id": incident_id, "run_id": model_run_id, "outcome": outcome, "judge_calls": judge,
                "p1_raw": {"usage": {"prompt_tokens": tokens - 100, "completion_tokens": 100, "total_tokens": tokens},
                           "rate_limit": {"attempt_count": 1 + rate_limited,
                                          "rate_limit_rejections": ["429"] * rate_limited}},
                "incident_field_scores": {}, "ground_truth": {}}
    return run_one


GT = {"status": "candidate", "version": "ground-truth-v1.0", "manifest": {"records_sha256": "g"},
      "split": {"version": "split-v2"},
      "by_incident_id": {i: {"category": "Assault", "filename": f"{i}.mp4", "p1_shaped": {}} for i in SPLIT["dev"]}}


def _stage(configs, tmp_path, **kwargs):
    return er.run_stage(configs, split=SPLIT, gt_index=GT, store=FakeStore(),
                        video_source=lambda i: ("u", {"r2_object_key": i, "duration_seconds": 10.0}),
                        call_factory_for=lambda c: (lambda *a, **k: (lambda *b: OUTCOME)), confirm_paid=True,
                        results_root=tmp_path, now=datetime(2026, 11, 1, tzinfo=UTC), log=lambda *_: None,
                        pricing=PRICING, **{"run_one": _fake_run_one(), **kwargs})


# --- D10 -----------------------------------------------------------------------------------------

def test_the_schedule_is_deterministic_interleaved_and_rotating():
    configs = [_config("cfg-c1"), _config("cfg-c2")]
    order = er.schedule(configs, SPLIT["dev"], 2)
    assert order == er.schedule(configs, list(reversed(SPLIT["dev"])), 2)  # input order does not matter
    assert len(order) == 2 * 4 * 2
    first = [k for _, position, _, k in order[::2]]
    assert set(first) == {0, 1}  # neither configuration always goes first
    for repeat in (1, 2):
        per_video = [v for r, _, v, _ in order if r == repeat][::2]
        assert sorted(per_video) == sorted(SPLIT["dev"])
    assert er.schedule(configs, SPLIT["dev"], 2, seed=1) != order


def test_a_stage_runs_configurations_interleaved_and_logs_every_call(tmp_path):
    out = _stage([_config("cfg-c1"), _config("cfg-c2", arm="vss", pipeline={"profile": "accuracy", "skip_rp1": True,
                                                                    "skip_crops": True, "agent_base_url": "http://a"})],
                 tmp_path)
    assert out["stopped"] is None and all(r["complete"] for r in out["records"])
    log = [json.loads(line) for line in (Path(out["stage_dir"]) / "cost-log.jsonl").read_text().splitlines()]
    assert len(log) == 16 and {e["config"] for e in log[:2]} == {"cfg-c1", "cfg-c2"}
    assert log[-1]["config_cumulative"]["p1_tokens"] == 8 * 9000
    record = out["records"][0]
    assert record["usage"]["p1_calls"] == 8 and record["usage"]["judge_calls"] == 24
    assert record["usage"]["cost_usd_provisional"] == pytest.approx(8 * (9000 / 1e6 * 10 + 3000 / 1e6 * 10))
    assert record["usage"]["pricing_provisional"] is True
    schedule = json.loads((Path(out["stage_dir"]) / "schedule.json").read_text())
    assert schedule["seed"] == er.ORDER_SEED and len(schedule["order"]) == 16


def test_a_stage_needs_the_same_videos_and_repeats(tmp_path):
    with pytest.raises(er.ExperimentRefused, match="share"):
        _stage([_config("cfg-c1"), _config("cfg-c2", repeats=1, budget={"max_p1_calls": 4, "max_p1_tokens": 84000,
                                                                "max_judge_calls": 40})], tmp_path)


@pytest.mark.parametrize("budget, run_one, reason", [
    ({"max_p1_calls": 8, "max_p1_tokens": 100000, "max_judge_calls": 80}, _fake_run_one(tokens=20000), "max_p1_tokens"),
    ({"max_p1_calls": 8, "max_p1_tokens": 8 * er.P1_TOKENS_CEILING, "max_judge_calls": 80}, _fake_run_one(rate_limited=1),
     "rate limited"),
])
def test_hard_caps_stop_the_stage_and_keep_partial_results(tmp_path, budget, run_one, reason):
    out = _stage([_config("cfg-c1", budget=budget)], tmp_path, run_one=run_one)
    assert reason in out["stopped"]["reason"]
    record = json.loads(Path(out["results_files"][0]).read_text())
    assert record["complete"] is False and record["stopped"]["reason"] == out["stopped"]["reason"]
    assert record["usage"]["p1_calls"] < 8  # stopped before the plan was finished


def test_a_judge_cap_below_the_plans_worst_case_is_refused_before_any_call(tmp_path):
    with pytest.raises(er.ExperimentRefused, match="max_judge_calls 6 is below"):
        _stage([_config("cfg-c1", budget={"max_p1_calls": 8, "max_p1_tokens": 8 * er.P1_TOKENS_CEILING,
                                          "max_judge_calls": 6})], tmp_path, run_one=_fake_run_one(judge=3))


def test_a_plan_that_cannot_fit_its_token_cap_is_refused_before_any_call(tmp_path):
    with pytest.raises(er.ExperimentRefused, match="max_p1_tokens"):
        _stage([_config("cfg-c1", budget={"max_p1_calls": 8, "max_p1_tokens": 50000, "max_judge_calls": 80})], tmp_path)


def test_every_config_needs_all_three_hard_caps():
    config = _config("cfg-c1", budget={"max_p1_calls": 8})
    problems = er.config_problems(config)
    assert any("max_p1_tokens" in p for p in problems) and any("max_judge_calls" in p for p in problems)


# --- pilot ------------------------------------------------------------------------------------

def test_a_pilot_is_never_reportable_and_its_report_hides_accuracy(tmp_path):
    frozen = {**GT, "status": "frozen"}
    out = er.run_stage([_config("pilot-x", purpose="pilot")], split=SPLIT, gt_index=frozen, store=FakeStore(),
                       video_source=lambda i: ("u", {}), call_factory_for=lambda c: (lambda *a, **k: (lambda *b: OUTCOME)),
                       run_one=_fake_run_one(), confirm_paid=True, results_root=tmp_path,
                       now=datetime(2026, 11, 1, tzinfo=UTC), log=lambda *_: None, pricing=PRICING)
    record = out["records"][0]
    assert record["purpose"] == "pilot" and record["reportable"] is False  # even on frozen ground truth
    text = rep.render({"pilot": record}, title="pilot")
    assert "PILOT" in text and "## Incident fields" not in text and "## Paired comparisons" not in text
    assert "## Usage and gateway cost" in text and "## Latency" in text


def test_pilot_configs_are_dev_only_and_never_final():
    assert any("pilot" in p for p in er.config_problems(_config("pilot-y", purpose="pilot", frozen_baseline=True)))


def test_the_committed_pilot_configs_allow_candidate_gt_only_as_pilots():
    for path in sorted(er.CONFIG_DIR.glob("*.json")):
        config = er.load_config(path)
        assert config["ground_truth"]["allow_candidate"] == (config["purpose"] == "pilot"), path.name


# --- D9 v2 ------------------------------------------------------------------------------------

def _video(incident_id, *, fields=None, items=None, outcome="scored", oot=False, repeat=1):
    fields = fields or {}
    scores = {f: {"pass": fields.get(f, True)} for f in sel.INCIDENT_SCORES}
    video = {"incident_id": incident_id, "outcome": outcome, "repeat": repeat, "incident_field_scores": scores,
             "ground_truth": {"incident": {"out_of_taxonomy": oot}}}
    for kind in sel.ITEM_KINDS:
        tp, fp, fn = (items or {}).get(kind, (1, 0, 0))
        video[kind] = {"matches": [{}] * tp, "unmatched_model": [{}] * fp, "unmatched_gt": [{}] * fn}
    return video


def _record(videos, prompt="p1-v4-base", **overrides):
    record = {"videos": videos, "prompt": {"id": prompt}, "plan": {"repeats": 1}, "model": "m",
              "ground_truth": {"records_sha256": "g"}, "split": {"half": "dev"}, "reportable": True,
              "complete": True, "purpose": "experiment"}
    record.update(overrides)
    return record


def test_item_f1_eligibility_and_empty_ground_truth():
    assert sel.item_f1(_video("A", items={"entities": (0, 0, 0)}), "entities") is None  # nothing to find or claim
    assert sel.item_f1(_video("A", items={"entities": (0, 2, 0)}), "entities") == 0.0  # GT empty, predictions made
    assert sel.item_f1(_video("A", items={"entities": (0, 0, 3)}), "entities") == 0.0  # GT present, none found
    assert sel.item_f1(_video("A", items={"entities": (1, 1, 0)}), "entities") == pytest.approx(2 / 3)
    assert sel.item_f1(_video("A", outcome="timeout"), "entities") is None  # no model output


def test_out_of_taxonomy_type_is_not_an_incident_component():
    video = _video("A", fields={"type": False}, oot=True)
    scores = sel.per_video(_record([video]))["A"]
    assert scores["type"] is None and scores["incident"] == 1.0  # the type miss does not count
    assert sel.per_video(_record([_video("A", fields={"type": False})]))["A"]["incident"] == pytest.approx(0.8)


def test_object_f1_is_the_mean_of_eligible_instrument_and_asset_f1():
    video = _video("A", items={"instruments": (0, 0, 0), "assets": (1, 1, 0)})
    assert sel.per_video(_record([video]))["A"]["object_f1"] == pytest.approx(2 / 3)


def test_repeats_are_averaged_before_pairing():
    record = _record([_video("A", fields={"severity_level": True}, repeat=1),
                      _video("A", fields={"severity_level": False}, repeat=2)], plan={"repeats": 2})
    assert sel.per_video(record)["A"]["severity_level"] == 0.5


def test_primary_is_the_equal_weight_mean_of_three_component_differences():
    base = _record([_video(f"V{i}", fields={"severity_level": False}, items={"entities": (0, 0, 2)}) for i in range(4)])
    cand = _record([_video(f"V{i}") for i in range(4)], prompt="p1-v4-e01-x")
    out = sel.compare(base, cand, resamples=200)
    assert out["point"]["incident"] == pytest.approx(0.2) and out["point"]["entity_f1"] == 1.0
    assert out["point"]["object_f1"] == 0.0
    assert out["point"]["primary"] == pytest.approx((0.2 + 1.0 + 0.0) / 3, abs=1e-4)
    assert out["point"]["eight"] == pytest.approx((1 / 8 + 1 / 8), abs=1e-4)  # secondary: severity and entity
    assert out == sel.compare(base, cand, resamples=200)  # seeded bootstrap


def test_selection_needs_the_minimum_improvement_and_falls_back_to_the_baseline(monkeypatch):
    monkeypatch.setattr(sel.prompt_registry, "prompt_text", lambda prompt_id, registry=None: "x" * len(prompt_id))
    registry = {"prompts": [{"id": "p1-v4-base"}, {"id": "p1-v4-e01-a"}, {"id": "p1-v4-e02-b"}]}
    base = _record([_video(f"V{i}", fields={"severity_level": i > 0}) for i in range(10)])
    small = _record([_video(f"V{i}") for i in range(10)], prompt="p1-v4-e01-a")  # incident +0.02 -> primary < 0.02
    out = sel.evaluate(base, {"a": small}, registry=registry, resamples=100)
    assert out["candidates"][0]["primary"] < sel.MIN_IMPROVEMENT and out["selected"] == "p1-v4-base"


def test_guardrails_block_credible_regressions_and_lost_outputs():
    base = _record([_video(f"V{i}") for i in range(10)])
    worse = _record([_video(f"V{i}", fields={"start_timestamp": False}) for i in range(10)], prompt="p1-v4-e01-a")
    comparison = sel.compare(base, worse, resamples=100)
    assert any(p.startswith("G2: start_timestamp") for p in sel.guardrails(base, worse, comparison))
    lossy = _record([_video(f"V{i}", outcome="contract_invalid" if i < 2 else "scored") for i in range(10)],
                    prompt="p1-v4-e01-a")
    assert any(p.startswith("G1") for p in sel.guardrails(base, lossy, sel.compare(base, lossy, resamples=50)))
    other = _record([_video(f"V{i}") for i in range(10)], prompt="p1-v4-e01-a", model="other")
    assert any("G3: different model" in p for p in sel.guardrails(base, other, sel.compare(base, other, resamples=50)))


def test_ties_are_broken_by_the_documented_order(monkeypatch):
    monkeypatch.setattr(sel.prompt_registry, "prompt_text", lambda prompt_id, registry=None: "x" * len(prompt_id))
    registry = {"prompts": [{"id": "p1-v4-base"}, {"id": "p1-v4-e01-a"}, {"id": "p1-v4-e02-bb"}]}
    base = _record([_video(f"V{i}", items={"entities": (0, 0, 1)}) for i in range(10)])
    a = _record([_video(f"V{i}") for i in range(10)], prompt="p1-v4-e01-a")
    b = _record([_video(f"V{i}") for i in range(10)], prompt="p1-v4-e02-bb")
    out = sel.evaluate(base, {"a": a, "b": b}, registry=registry, resamples=50)
    assert out["tie_break_used"] and out["selected"] == "p1-v4-e01-a"  # identical scores: the shorter prompt


@pytest.mark.parametrize("overrides, match", [({"split": {"half": "test"}}, "dev results only"),
                                              ({"purpose": "pilot"}, "pilot"),
                                              ({"reportable": False}, "not reportable"),
                                              ({"complete": False}, "did not complete")])
def test_selection_refuses_test_pilot_unfrozen_and_incomplete_records(tmp_path, overrides, match):
    decisions = tmp_path / "decisions.md"
    decisions.write_text("### rule\n")
    base = _record([_video("V1")])
    bad = copy.deepcopy(_record([_video("V1")], prompt="p1-v4-e01-a"))
    bad.update(overrides)
    with pytest.raises(sel.SelectionRefused, match=match):
        sel.select_d9(base, {"bad": bad}, rule_record="rule", decisions_path=decisions)
    with pytest.raises(sel.SelectionRefused, match="pre-registered"):
        sel.select_d9(base, {}, rule_record="missing", decisions_path=decisions)


# --- retry-proof caps -------------------------------------------------------------------------

def test_retries_draw_on_the_request_cap_and_never_exceed_it(tmp_path):
    seen = []

    def factory_for(config):
        def factory(incident_id, run_id, duration, max_retries=None):
            seen.append(max_retries)
            return lambda *b: OUTCOME
        return factory

    tight = _config("cfg-tight", repeats=1, budget={"max_p1_calls": 4, "max_p1_tokens": 4 * er.P1_TOKENS_CEILING,
                                                    "max_judge_calls": 80})
    er.run_stage([tight], split=SPLIT, gt_index=GT, store=FakeStore(), video_source=lambda i: ("u", {}),
                 call_factory_for=factory_for, run_one=_fake_run_one(), confirm_paid=True, results_root=tmp_path,
                 now=datetime(2026, 11, 1, tzinfo=UTC), log=lambda *_: None, pricing=PRICING)
    assert seen == [0, 0, 0, 0]  # 4 runs, 4 requests allowed: no room for a single retry
    seen.clear()
    roomy = _config("cfg-roomy", repeats=1, budget={"max_p1_calls": 5, "max_p1_tokens": 10 * er.P1_TOKENS_CEILING,
                                                    "max_judge_calls": 80})
    er.run_stage([roomy], split=SPLIT, gt_index=GT, store=FakeStore(), video_source=lambda i: ("u", {}),
                 call_factory_for=factory_for, run_one=_fake_run_one(), confirm_paid=True, results_root=tmp_path,
                 now=datetime(2026, 11, 2, tzinfo=UTC), log=lambda *_: None, pricing=PRICING)
    assert seen[0] == 1 and max(seen) <= er.P1_RATE_LIMIT_RETRIES


def test_rate_limited_honours_a_lower_retry_allowance():
    from eval_vlm_client import P1_RATE_LIMIT_POLICY, ChatResult, P1Pacer, rate_limited

    assert er.P1_RATE_LIMIT_RETRIES == P1_RATE_LIMIT_POLICY["max_rate_limit_retries"]
    no_wait = P1Pacer(sleep=lambda _s: None)
    calls = []

    def always_429():
        calls.append(1)
        return ChatResult(ok=False, status_code=429, failure_kind="rate_limited")

    for allowance, expected in ((0, 1), (1, 2), (5, 1 + P1_RATE_LIMIT_POLICY["max_rate_limit_retries"]), (None, 3)):
        calls.clear()
        outcome = rate_limited(always_429, pacer=no_wait, max_retries=allowance)
        assert len(calls) == expected == outcome.summary()["attempt_count"]


def test_unmetered_attempts_count_at_the_ceiling_and_429s_at_zero():
    timeout = {"p1_raw": {"ok": False, "failure_kind": "timeout", "usage": {},
                          "rate_limit": {"attempts": [{"failure_kind": "timeout"}]}}, "judge_calls": 0}
    assert er.call_usage(timeout, PRICING, "m")["p1_tokens_bound"] == er.P1_TOKENS_CEILING
    retried = {"p1_raw": {"ok": True, "failure_kind": None, "usage": {"total_tokens": 9000},
                          "rate_limit": {"attempts": [{"failure_kind": "rate_limited"}, {"failure_kind": None}]}},
               "judge_calls": 2, "judge_tokens": 700}
    usage = er.call_usage(retried, PRICING, "m")
    assert usage["p1_attempts"] == 2 and usage["p1_tokens_bound"] == 9000 and usage["judge_tokens"] == 700
    assert usage["cost_usd_provisional"] == pytest.approx(9000 / 1e6 * 10 + 700 / 1e6 * 10)


def test_the_judge_worst_case_counts_every_judged_field_and_retry():
    gt = {"entities": [{}] * 2, "instruments": [{}], "assets": [{}] * 3}
    assert er.worst_judge_attempts(gt, "full") == (1 + 2 + 2 + 6) * er.JUDGE_ATTEMPTS_PER_FIELD
    assert er.worst_judge_attempts(gt, "incident_only") == er.JUDGE_ATTEMPTS_PER_FIELD
    assert er.JUDGE_ATTEMPTS_PER_FIELD == 5


def test_judge_tokens_are_measured_from_the_endpoint(monkeypatch):
    import eval_gt

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": '{"score": 0.9}'}}], "usage": {"total_tokens": 321}}

    monkeypatch.setattr(eval_gt.config, "llm_base_url", lambda: "http://judge.invalid/v1")
    monkeypatch.setattr(eval_gt.httpx, "post", lambda *a, **k: Response())
    before = eval_gt.JUDGE_TOKENS
    assert eval_gt.judge_description_similarity("a", "b").ok
    assert eval_gt.JUDGE_TOKENS - before == 321


def test_experiments_must_be_fully_scored_and_pilots_may_score_incidents_only():
    assert any("scored in full" in p for p in er.config_problems(_config("cfg-x", scoring="incident_only")))
    assert er.config_problems(_config("pilot-z", purpose="pilot", scoring="incident_only")) == []


def test_eligible_counts_are_reported_as_the_denominators():
    base = _record([_video("V1", oot=True), _video("V2", items={"entities": (0, 0, 0)}), _video("V3")])
    cand = _record([_video("V1", oot=True), _video("V2"), _video("V3")], prompt="p1-v4-e01-x")
    eligible = sel.compare(base, cand, resamples=20)["eligible"]
    assert eligible["paired"]["type"] == 2 and eligible["paired"]["incident"] == 3  # OOT drops type only
    assert eligible["baseline"]["entity_f1"] == 2 and eligible["candidate"]["entity_f1"] == 3
    assert eligible["paired"]["entity_f1"] == 2 and eligible["out_of_taxonomy_videos"] == 1
