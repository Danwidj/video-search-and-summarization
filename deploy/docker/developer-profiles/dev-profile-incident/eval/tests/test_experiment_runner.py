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

"""Two-arm experiment runner (PR 6A): guards, Track X response handling, arm parity and a mock C1-C4 plumbing run.

Hermetic: fake transports, a fake judge and embedder, a synthetic frozen ground truth. No call leaves the process.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import contract
import eval_gt
import experiment_runner as er
import matching
import prompt_registry as pr
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_experiment  # noqa: E402
import eval_gt_schema  # noqa: E402
import eval_run  # noqa: E402
import ground_truth_freeze as gtf  # noqa: E402
from eval_vlm_client import ChatResult, P1Outcome  # noqa: E402
from test_ground_truth_freeze import _write  # noqa: E402
from test_offline_store import _fake_embed, _fake_judge  # noqa: E402

MODEL = "nvidia/cosmos-3-super-reasoner"
SPLIT = {"version": "split-v2", "dev": ["Assault001", "Burglary002"], "test": []}
SELECTED = "p1-v4-e01-plumbing"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    directory = tmp_path / "experiments"
    shutil.copytree(pr.REGISTRY_DIR, directory)
    monkeypatch.setattr(pr, "REGISTRY_DIR", directory)
    monkeypatch.setattr(pr, "REGISTRY_PATH", directory / "registry.json")
    pr.add(SELECTED, parent=pr.BASE_ID, text=contract.extraction_prompt() + "\nBe precise.", hypothesis="plumbing",
           created="2026-10-27")
    return pr.load()


@pytest.fixture
def decisions(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text("# Log\n\n### 2026-11-01: Stage 2 selection is p1-v4-e01-plumbing\n- **Decision:** ...\n")
    return path


def _config(**overrides):
    config = {"experiment_id": "plumb-c1", "description": "", "arm": "direct-vlm", "prompt_id": pr.BASE_ID,
              "model": MODEL, "split": "dev", "ground_truth": {"dir": "gt", "allow_candidate": False}, "repeats": 1,
              "budget": {"max_p1_calls": 10, "max_p1_tokens": 210000, "max_judge_calls": 100}, "purpose": "experiment",
              "pipeline": {"profile": "accuracy", "skip_rp1": True, "skip_crops": True,
                                                            "agent_base_url": None},
              "frozen_baseline": False, "final": False, "selection_record": None, "baseline_ref": None, "videos": None, "scoring": "full"}
    for key, value in overrides.items():
        config[key] = value
    return config


def _vss(**overrides):
    return _config(arm="vss", pipeline={"profile": "accuracy", "skip_rp1": True, "skip_crops": True,
                                        "agent_base_url": "http://agent.test"}, **overrides)


def test_a_dev_config_is_valid(registry, decisions):
    assert er.config_problems(_config(), registry=registry, decisions_path=decisions) == []
    assert er.config_problems(_vss(prompt_id=SELECTED), registry=registry, decisions_path=decisions) == []


@pytest.mark.parametrize("overrides, problem", [
    ({"split": "test"}, "pre-registered"),
    ({"split": "test", "final": True}, "selection record"),
    ({"split": "test", "final": True, "selection_record": "2026-11-01: something else"}, "selection record"),
    ({"final": True}, "test split only"),
    ({"prompt_id": "p1-v4-e42-missing"}, "not in the prompt registry"),
    ({"model": "gpt-4o"}, "allowlist"),
    ({"repeats": 0}, "repeats"),
    ({"pipeline": {"profile": "accuracy", "skip_rp1": True, "skip_crops": False, "agent_base_url": None}}, "skip_crops"),
    ({"pipeline": {"profile": "accuracy", "skip_rp1": False, "skip_crops": True, "agent_base_url": None}}, "skip_rp1"),
    ({"arm": "vss"}, "agent_base_url"),
    ({"surprise": 1}, "keys must be exactly"),
])
def test_config_guards(registry, decisions, overrides, problem):
    assert any(problem in p for p in er.config_problems(_config(**overrides), registry=registry,
                                                        decisions_path=decisions))


def test_the_test_split_opens_only_after_a_recorded_selection(registry, decisions):
    final = _config(split="test", final=True, selection_record="2026-11-01: Stage 2 selection is p1-v4-e01-plumbing")
    assert er.config_problems(final, registry=registry, decisions_path=decisions) == []


def test_budget_and_frozen_baseline_guards(registry, decisions, tmp_path):
    with pytest.raises(er.ExperimentRefused, match="exceed"):
        er.preflight(_config(repeats=6), SPLIT, registry=registry, decisions_path=decisions)
    frozen = _config(frozen_baseline=True)
    done = tmp_path / "results" / "plumb-c1" / "20261101T000000Z"
    done.mkdir(parents=True)
    (done / "results.json").write_text(json.dumps({"complete": True}))
    with pytest.raises(er.ExperimentRefused, match="frozen baseline"):
        er.preflight(frozen, SPLIT, registry=registry, results_root=tmp_path / "results", decisions_path=decisions)


def test_nothing_is_sent_without_confirmation(registry, decisions, tmp_path):
    def never(*_):
        raise AssertionError("a call was made")
    result = er.run_experiment(_config(), split=SPLIT, gt_index={}, store=None, video_source=never, call_factory=never,
                               run_one=never, confirm_paid=False, results_root=tmp_path, registry=registry,
                               decisions_path=decisions)
    assert result["dry_run"] and result["plan"]["planned_p1_calls"] == 2


def _report(incident_type: str, start: int, end: int) -> str:
    report = json.loads((contract.CONTRACTS_DIR / "fixtures" / "valid" / "minimal-report.json").read_text())
    report["incident"].update({"type": incident_type, "start_timestamp": start, "end_timestamp": end,
                               "description": "Two people fight."})
    report["timeline"] = [{"start_seconds": start, "end_seconds": end, "description": "They fight."}]
    return json.dumps(report)


def _response(status, body):
    return er.VSSResponse(status, body, 1.5)


def _agent_body(content, **extra):
    return {"raw_output": content, "contract_version": contract.contract_version(), "finish_reason": "stop",
            "model": MODEL, **extra}


def test_vss_responses_follow_the_track_x_rules():
    base = {"prompt_id": pr.BASE_ID, "prompt_sha256": "x", "started_at": "s", "finished_at": "f"}
    ok = er.vss_chat_result(_response(200, _agent_body("{}")), **base)
    assert ok.ok and ok.content == "{}" and ok.raw["agent"]["status_code"] == 200
    rejected = er.vss_chat_result(_response(422, {"detail": _agent_body("{bad")}), **base)
    assert rejected.ok and rejected.content == "{bad"  # the agent's rejection never replaces core-scored-v1
    for status, body, kind in ((422, {"detail": [{"msg": "missing"}]}, "http_error"), (504, {"detail": "t"}, "timeout"),
                               (429, {}, "rate_limited"), (500, {"detail": "x"}, "http_error")):
        result = er.vss_chat_result(_response(status, body), **base)
        assert not result.ok and result.failure_kind == kind
    timeout = er.vss_chat_result(er.VSSResponse(None, None, 300.0, "ReadTimeout", timed_out=True), **base)
    assert timeout.failure_kind == "timeout"
    wrong = er.vss_chat_result(_response(200, {**_agent_body("{}"), "contract_version": "incident-contract-v3"}), **base)
    assert not wrong.ok and "contract_version" in wrong.error


def test_a_vss_experiment_prompt_counts_only_when_the_agent_confirms_it(registry):
    item = pr.entry(SELECTED, registry)
    kwargs = {"prompt_id": item["id"], "prompt_sha256": item["sha256"], "started_at": "s", "finished_at": "f"}
    unconfirmed = er.vss_chat_result(_response(200, _agent_body("{}")), **kwargs)
    assert not unconfirmed.ok and "did not confirm" in unconfirmed.error
    confirmed = er.vss_chat_result(_response(200, _agent_body("{}", experiment={"prompt_id": item["id"],
                                                                                "prompt_sha256": item["sha256"]})),
                                   **kwargs)
    assert confirmed.ok


def test_vss_request_is_p1_only_without_crops_and_names_the_prompt(registry):
    sent = []

    def post(url, payload, *, timeout):
        sent.append((url, payload))
        return _response(200, _agent_body("{}"))

    class NoWait:
        def wait(self, _):
            return 0.0

        def sleep(self, _):
            pass

        def mark_end(self):
            pass

    for prompt in (pr.BASE_ID, SELECTED):
        er.vss_call(_vss(prompt_id=prompt), pr.entry(prompt, registry), incident_id="Assault001", run_id="Xv1-abc",
                    duration=30.0, pacer=NoWait(), post=post)(MODEL, "https://signed")
    (url, base), (_, experiment) = sent
    assert url == "http://agent.test/api/v1/incidents/Assault001/analyze"
    assert base == {"video_url": "https://signed", "model": MODEL, "model_run_id": "Xv1-abc", "skip_rp1": True,
                    "skip_crops": True, "video_duration_seconds": 30.0}
    assert experiment["experiment_prompt_id"] == SELECTED


@pytest.fixture
def frozen(tmp_path):
    directory = _write(tmp_path / "gt")
    return eval_gt_schema.load_frozen_gt_index(directory), gtf.read_frozen(directory)["sheets"]


def _score(frozen, p1_call, *, run_id="MR-1"):
    index, sheets = frozen
    store = eval_experiment.frozen_store(sheets)
    store.insert_model_run(run_id, model_name=MODEL)
    entry = index["by_incident_id"]["Assault001"]
    with patch.object(matching, "embed_texts", side_effect=_fake_embed), \
            patch.object(eval_gt, "judge_description_similarity", side_effect=_fake_judge):
        return eval_run.run_one_video(
            store, model=MODEL, category=entry["category"], filename=entry["filename"], incident_id="Assault001",
            r2_object_key="k", video_url="u", gt_p1_shaped=entry["p1_shaped"], model_run_id=run_id,
            split_manifest_ref="split-v2.json", video_duration_seconds=30.0, incident_only=True, p1_call=p1_call)


def test_both_arms_score_the_same_raw_output_identically(frozen):
    content = _report("assault", 2, 9)
    direct = _score(frozen, lambda *_: P1Outcome(ChatResult(ok=True, content=content, finish_reason="stop"), []))
    vss_result = er.vss_chat_result(_response(200, _agent_body(content)), prompt_id=pr.BASE_ID, prompt_sha256="x",
                                    started_at="s", finished_at="f")
    vss = _score(frozen, lambda *_: P1Outcome(vss_result, []))
    assert direct["incident_field_scores"] == vss["incident_field_scores"]
    assert direct["outcome"] == vss["outcome"] == "scored"
    assert direct["prediction"] == vss["prediction"]


def test_candidate_ground_truth_is_refused_for_a_real_run(registry, decisions, tmp_path):
    with pytest.raises(er.ExperimentRefused, match="not frozen"):
        er.run_experiment(_config(), split=SPLIT, gt_index={"status": "candidate"}, store=None, video_source=None,
                          call_factory=None, run_one=None, confirm_paid=True, results_root=tmp_path, registry=registry,
                          decisions_path=decisions)


def test_mock_plumbing_run_of_c1_to_c4_gives_the_four_paired_comparisons(registry, decisions, frozen, tmp_path):
    index, sheets = frozen
    configs = {"C1": _config(experiment_id="plumb-c1"), "C2": _vss(experiment_id="plumb-c2"),
               "C3": _vss(experiment_id="plumb-c3", prompt_id=SELECTED),
               "C4": _config(experiment_id="plumb-c4", prompt_id=SELECTED)}
    selected = pr.entry(SELECTED, registry)
    windows = {"Assault001": ("assault", 2, 9), "Burglary002": ("burglary", 0, 20)}

    def factory_for(name):
        def factory(incident_id, run_id, duration, max_retries=None):
            kind, start, end = windows[incident_id]
            if name in ("C1", "C2") and incident_id == "Burglary002":
                kind = "assault"  # the baseline prompt gets the type wrong on one video
            content = _report(kind, start, end)
            if configs[name]["arm"] == "direct-vlm":
                return lambda *_: P1Outcome(ChatResult(ok=True, content=content, finish_reason="stop"), [])
            echo = {"experiment": {"prompt_id": SELECTED, "prompt_sha256": selected["sha256"]}} if name == "C3" else {}
            result = er.vss_chat_result(_response(200, _agent_body(content, **echo)),
                                        prompt_id=configs[name]["prompt_id"],
                                        prompt_sha256=pr.entry(configs[name]["prompt_id"], registry)["sha256"],
                                        started_at="s", finished_at="f")
            return lambda *_: P1Outcome(result, [])
        return factory

    def run_one(*args, **kwargs):
        kwargs["incident_only"] = True
        return eval_run.run_one_video(*args, **kwargs)

    records = {}
    with patch.object(matching, "embed_texts", side_effect=_fake_embed), \
            patch.object(eval_gt, "judge_description_similarity", side_effect=_fake_judge):
        for name, config in configs.items():
            out = er.run_experiment(
                {**config, "ground_truth": {"dir": "gt", "allow_candidate": False}}, split=SPLIT, gt_index=index,
                store=eval_experiment.frozen_store(sheets),
                video_source=lambda i: ("https://signed", {"r2_object_key": i, "duration_seconds": 30.0}),
                call_factory=factory_for(name), run_one=run_one, confirm_paid=True, results_root=tmp_path / "results",
                registry=registry, decisions_path=decisions, now=datetime(2026, 11, 1, tzinfo=UTC), log=lambda *_: None)
            records[name] = json.loads(Path(out["results"]).read_text())
            assert records[name]["complete"] and records[name]["reportable"]
            assert records[name]["prompt"]["sha256"] == pr.entry(config["prompt_id"], registry)["sha256"]
            assert (Path(out["results"]).parent / "prompt.txt").read_text() == pr.prompt_text(config["prompt_id"])
    table = er.four_way(records)
    assert table["problems"] == []
    assert set(table["comparisons"]) == {"C2-C1", "C3-C2", "C4-C1", "C3-C4", "C3-C1"}
    type_effect = {name: c["fields"]["type"]["mean_difference"] for name, c in table["comparisons"].items()}
    assert type_effect == {"C2-C1": 0.0, "C3-C2": 0.5, "C4-C1": 0.5, "C3-C4": 0.0, "C3-C1": 0.5}
    with pytest.raises(er.ExperimentRefused, match="immutable"):
        er.run_experiment(configs["C1"], split=SPLIT, gt_index=index, store=None, video_source=None,
                          call_factory=None, run_one=None, confirm_paid=True, results_root=tmp_path / "results",
                          registry=registry, decisions_path=decisions, now=datetime(2026, 11, 1, tzinfo=UTC))


def test_mismatched_configurations_are_reported():
    def record(arm, prompt, sha, model=MODEL):
        return {"arm": arm, "model": model, "prompt": {"id": prompt, "sha256": sha},
                "ground_truth": {"records_sha256": "g"}, "split": {"half": "test"},
                "methodology": {"methodology_version": "m"}, "videos": [{"incident_id": "A"}]}
    records = {"C1": record("direct-vlm", pr.BASE_ID, "b"), "C2": record("vss", pr.BASE_ID, "b"),
               "C3": record("vss", SELECTED, "s"), "C4": record("direct-vlm", SELECTED, "t", model="other")}
    problems = er.configuration_problems(records)
    assert any("model" in p for p in problems) and any("byte-identical" in p for p in problems)
    swapped = copy.deepcopy(records)
    swapped["C2"]["arm"] = "direct-vlm"
    assert any("C2 must be the vss arm" in p for p in er.configuration_problems(swapped))


def test_committed_configs_are_valid_dev_runs():
    for path in sorted(er.CONFIG_DIR.glob("*.json")):
        config = er.load_config(path)
        assert er.config_problems(config) == [], path.name
        if path.name.startswith("s3-"):  # the final test configs, checked in test_stage3.py
            assert config["split"] == "test" and config["final"] and config["frozen_baseline"]
            continue
        if path.name.startswith("e2e-"):  # the end-to-end profile configs, checked in test_e2e_profile.py
            assert config["purpose"] == "profile" and not config["final"] and config["frozen_baseline"]
            continue
        assert config["split"] == "dev" and not config["final"]
        if config["pipeline"]["profile"] == "end-to-end":
            assert config["experiment_id"].startswith("pilot-")  # cropping only in the pilot (and the later profile)
        assert er.planned_calls(config, json.loads(er.SPLIT_PATH.read_text())) <= config["budget"]["max_p1_calls"]
