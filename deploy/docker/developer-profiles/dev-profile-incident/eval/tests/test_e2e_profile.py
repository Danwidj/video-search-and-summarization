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

"""The end-to-end VSS profile: config rules, the crop budget, no scoring, and Stage 3 left untouched.

Hermetic: fake transports and synthetic records. Nothing is sent.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import e2e_profile
import eval_gt
import experiment_runner as er

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_run  # noqa: E402
from eval_vlm_client import ChatResult, P1Outcome  # noqa: E402

RECORD = "2026-11-01: Stage 2 selection is p1-v4-base"
SPLIT = {"version": "split-v2", "dev": [], "test": ["A1", "A2", "A3"]}
PRICING = {"provisional": True, "source": "test", "usd_per_million_tokens": {"default": 0.0},
           "judge_model": "judge", "judge_tokens_per_call_estimate": 1000}
GT = {"status": "frozen", "version": "ground-truth-v1.0", "manifest": {"records_sha256": "g"},
      "split": {"version": "split-v2"},
      "by_incident_id": {i: {"category": "Assault", "filename": f"{i}.mp4", "p1_shaped": {"entities": [{}]}}
                         for i in SPLIT["test"]}}


@pytest.fixture
def decisions(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text(f"# Log\n\n### {RECORD}\n- **Decision:** ...\n")
    return path


def _profile(name="e2e-c2-test", **overrides):
    config = {"experiment_id": name, "description": "", "arm": "vss", "prompt_id": "p1-v4-base",
              "model": "nvidia/cosmos-3-super-reasoner", "split": "test",
              "ground_truth": {"dir": "gt", "allow_candidate": False}, "repeats": 1,
              "budget": {"max_p1_calls": 9, "max_p1_tokens": 9 * er.P1_TOKENS_CEILING, "max_judge_calls": 0,
                         "max_crop_calls": 3 * 10 + 20, "max_crop_tokens": (3 * 10 + 20) * er.CROP_TOKENS_CEILING},
              "pipeline": {"profile": "end-to-end", "skip_rp1": True, "skip_crops": False,
                           "max_crop_calls_per_request": 10, "request_timeout_s": 900,
                           "agent_base_url": "http://agent.test", "retry_policy": "retry-v2"},
              "frozen_baseline": True, "final": False, "selection_record": RECORD, "baseline_ref": None,
              "videos": None, "purpose": "profile", "scoring": "none"}
    config.update(overrides)
    return config


def _with_pipeline(**changes):
    return {"pipeline": {**_profile()["pipeline"], **changes}}


def test_a_profile_config_is_valid_on_test_without_being_final(decisions):
    assert er.config_problems(_profile(), decisions_path=decisions) == []


@pytest.mark.parametrize("overrides, problem", [
    (_with_pipeline(skip_crops=True), "cropping on"),
    (_with_pipeline(max_crop_calls_per_request=None), "max_crop_calls_per_request"),
    (_with_pipeline(max_crop_calls_per_request=500), "max_crop_calls_per_request"),
    (_with_pipeline(request_timeout_s=10), "request_timeout_s"),
    (_with_pipeline(profile="accuracy"), "pipeline.profile end-to-end"),
    ({"scoring": "full", "budget": {**_profile()["budget"], "max_judge_calls": 10}}, "never scored"),
    ({"budget": {**_profile()["budget"], "max_judge_calls": 5}}, "must be 0"),
    ({"budget": {k: v for k, v in _profile()["budget"].items() if k != "max_crop_calls"}}, "max_crop_calls"),
    ({"final": True}, "never final"),
    ({"frozen_baseline": False}, "runs once"),
    ({"experiment_id": "s3-c2-vss-base"}, "starts with 'e2e-'"),
    ({"arm": "direct-vlm", "pipeline": {**_profile()["pipeline"], "agent_base_url": None}}, "vss arm only"),
    ({"selection_record": None}, "selection record"),
])
def test_profile_config_guards(decisions, overrides, problem):
    assert any(problem in p for p in er.config_problems(_profile(**overrides), decisions_path=decisions))


def test_an_accuracy_config_can_neither_profile_nor_skip_scoring(decisions):
    accuracy = _profile(purpose="experiment", scoring="none", final=True)
    assert any("profile only" in p for p in er.config_problems(accuracy, decisions_path=decisions))


def test_a_plan_beyond_the_crop_budget_is_refused_before_any_call(decisions):
    tight = _profile(budget={**_profile()["budget"], "max_crop_calls": 29})
    with pytest.raises(er.ExperimentRefused, match="max_crop_calls"):
        er.preflight(tight, SPLIT, decisions_path=decisions)


def test_the_profile_request_carries_the_cap_and_its_own_timeout():
    sent = []

    def post(url, payload, *, timeout):
        sent.append((payload, timeout))
        return er.VSSResponse(200, {"raw_output": "{}", "contract_version": "x"}, 1.0)

    pacer = SimpleNamespace(wait=lambda _: 0.0, sleep=lambda _: None, mark_end=lambda: None)
    er.vss_call(_profile(), {"id": "p1-v4-base", "sha256": "s"}, incident_id="A1", run_id="Xv1-a", duration=None,
                pacer=pacer, post=post)("m", "https://signed")
    payload, timeout = sent[0]
    assert payload["skip_crops"] is False and payload["max_crop_calls"] == 10 and timeout == 900


def _agent_outcome(crop):
    agent = {"p1_elapsed_ms": 20000.0, "end_to_end_s": 31.0, "experiment": {"crop": crop}}
    return P1Outcome(ChatResult(ok=True, content="{}", raw={"agent": agent}), [])


def _stage(configs, tmp_path, decisions, crop, seen_kwargs):
    def run_one(store, *, incident_id, model_run_id, p1_call, **kwargs):
        seen_kwargs.append(kwargs)
        p1_call("m", "u")
        return {"incident_id": incident_id, "run_id": model_run_id, "outcome": "scored", "judge_calls": 0,
                "p1_raw": {"ok": True, "usage": {"total_tokens": 9000}, "rate_limit": {"attempt_count": 1}}}

    return er.run_stage(configs, split=SPLIT, gt_index=GT, store=SimpleNamespace(insert_model_run=lambda *a, **k: None),
                        video_source=lambda i: ("u", {"r2_object_key": i, "duration_seconds": 10.0}),
                        call_factory_for=lambda c: (lambda *a, **k: (lambda *b: _agent_outcome(crop))),
                        run_one=run_one, confirm_paid=True, results_root=tmp_path / "results",
                        decisions_path=decisions, now=datetime(2026, 11, 1, tzinfo=UTC), log=lambda *_: None,
                        pricing=PRICING)


def test_a_profile_stage_meters_its_crop_calls_and_never_scores(tmp_path, decisions):
    crop = {"calls": 6, "tokens": 9000, "calls_without_usage": 1, "refused_by_cap": 0, "elapsed_ms": 9000.0}
    seen: list[dict] = []
    out = _stage([_profile(), _profile("e2e-c3-test")], tmp_path, decisions, crop, seen)
    assert out["stopped"] is None and all(r["complete"] for r in out["records"])
    usage = out["records"][0]["usage"]
    assert usage["crop_calls"] == 18 and usage["crop_tokens"] == 27000
    assert usage["crop_tokens_bound"] == 27000 + 3 * er.CROP_TOKENS_CEILING  # one unreported call per run
    assert usage["judge_calls"] == 0 and all(k.get("score") is False for k in seen)
    assert out["records"][0]["reportable"] is False and out["records"][0]["purpose"] == "profile"
    assert out["records"][0]["videos"][0]["transport"]["crop_cap"] == 10


def test_the_crop_budget_stops_the_stage_with_room_for_a_worst_case_run(tmp_path, decisions):
    config = _profile(budget={**_profile()["budget"], "max_crop_calls": 30})  # exactly the plan: no room for retries
    out = _stage([config], tmp_path, decisions, {"calls": 10, "tokens": 0}, [])
    assert "max_crop_calls" in out["stopped"]["reason"]


def test_an_attempt_that_may_have_cropped_unseen_counts_at_the_cap():
    result = {"transport": {"crop_cap": 40, "experiment": {"crop": {"calls": 5, "tokens": 5000}}}}
    usage = er.crop_usage(result, [{"failure_kind": "timeout"}, {"failure_kind": None}], unmetered=1)
    assert usage["crop_calls"] == 5 and usage["crop_calls_bound"] == 45
    assert usage["crop_tokens_bound"] == 5000 + 40 * er.CROP_TOKENS_CEILING
    assert er.crop_usage({"transport": {"p1_elapsed_ms": 1}}, [], 0) == {}  # an accuracy run has no crop usage


def test_an_unscored_run_validates_but_never_touches_the_store_or_the_judge(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("an unscored run made an evaluator call")

    monkeypatch.setattr(eval_gt, "judge_description_similarity", forbidden)
    monkeypatch.setattr(eval_run, "check_embedding_server_healthy", forbidden)
    content = json.dumps({"incident": {}})
    result = eval_run.run_one_video(
        None, model="m", category="Assault", filename="A1.mp4", incident_id="A1", r2_object_key="k",
        video_url="u", gt_p1_shaped={}, model_run_id="r", split_manifest_ref="split-v2.json",
        p1_call=lambda *_: P1Outcome(ChatResult(ok=True, content=content), []), score=False)
    assert result["scored"] is False and result["judge_calls"] == 0 and "incident_field_scores" not in result
    assert result["outcome"] in ("contract_invalid", "parse_failure")


def test_the_committed_profile_configs_are_stage3_c2_and_c3_with_cropping_on_15_seeded_clips():
    split = json.loads(er.SPLIT_PATH.read_text())
    configs = e2e_profile.load_configs()
    assert e2e_profile.setting_problems(configs, split) == []
    for config in configs.values():
        assert er.config_problems(config) == []
        assert er.preflight(config, split, results_root=Path("/nonexistent"))["planned_p1_calls"] == 15
    clips = e2e_profile.select_clips(split)
    assert clips == e2e_profile.select_clips(split) and len(clips) == 15 and set(clips) <= set(split["test"])


def test_the_committed_manifest_equals_a_fresh_build():
    try:
        e2e_profile.stage3_audit()
    except FileNotFoundError:
        pytest.skip("no Stage 3 audit on this host (the gitignored results are local)")
    committed = json.loads(e2e_profile.MANIFEST_PATH.read_text())
    fresh = e2e_profile.build_manifest(e2e_profile.load_configs(), json.loads(er.SPLIT_PATH.read_text()))
    assert e2e_profile.manifest_problems(committed, fresh) == []


def test_a_changed_or_missing_stage3_result_is_found(tmp_path):
    kept, changed = tmp_path / "kept.json", tmp_path / "changed.json"
    kept.write_text("{}")
    changed.write_text("{}")
    digest = e2e_profile.stage3.rec.sha256_file(kept)
    (tmp_path / "audit-20261030T000000Z.json").write_text(json.dumps({"ok": True, "files_sha256": {
        str(kept): digest, str(changed): digest, str(tmp_path / "gone.json"): digest}}))
    changed.write_text('{"edited": true}')
    problems = e2e_profile.stage3_problems(tmp_path)
    assert problems == [f"{changed}: changed since the Stage 3 audit", f"{tmp_path / 'gone.json'}: missing"]


def test_the_report_splits_latency_into_p1_cropping_and_the_rest():
    crop = {"elapsed_ms": 8000.0, "items": 4, "images": 3, "gaps": {"crop-call cap reached": 1}, "calls": 4,
            "cap_reached": True}
    video = {"outcome": "scored", "transport": {"end_to_end_s": 30.0, "p1_elapsed_ms": 20000.0,
                                                "experiment": {"crop": crop}}}
    row = e2e_profile.summarise({"experiment_id": "e2e-c2-vss-base", "videos": [video, {"outcome": "timeout"}]})
    assert row["latency_s"]["cropping"]["p50"] == 8.0 and row["latency_s"]["other_overhead"]["p50"] == 2.0
    assert row["cropping"]["image_rate"] == 0.75 and row["cropping"]["requests_at_cap"] == 1
