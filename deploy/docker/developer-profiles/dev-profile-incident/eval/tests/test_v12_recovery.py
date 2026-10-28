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

"""Methodology v1.2 preparation: matching calibration, offline re-matching, the retry policies, host-suspend
detection and the recovery-v1 protocol. Hermetic: fake clocks, fake embedder, fake calls."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_vlm_client as client  # noqa: E402
import experiment_recovery as rec  # noqa: E402
import experiment_runner as er  # noqa: E402
import experiment_selection as es  # noqa: E402
import item_rescore  # noqa: E402
import matching_calibration as mc  # noqa: E402
import methodology  # noqa: E402
import pytest  # noqa: E402


class Pacer:
    def __init__(self):
        self.slept = []

    def wait(self, _minimum):
        return 0.0

    def sleep(self, seconds):
        self.slept.append(seconds)

    def mark_end(self):
        pass


def _calls(*results):
    queue = list(results)
    return lambda: queue.pop(0)


FAIL = {k: client.ChatResult(ok=False, failure_kind=k, error=k) for k in ("timeout", "rate_limited", "http_error")}
OK = client.ChatResult(ok=True, content="{}")


# --- retry policies --------------------------------------------------------------------------------

def test_retry_v1_retries_only_rate_limits():
    out = client.rate_limited(_calls(FAIL["timeout"], OK), pacer=Pacer(), policy="retry-v1")
    assert out.result.failure_kind == "timeout" and len(out.attempts) == 1


def test_retry_v2_retries_timeouts_with_the_fixed_backoff():
    pacer = Pacer()
    out = client.rate_limited(_calls(FAIL["timeout"], FAIL["timeout"], OK), pacer=pacer, policy="retry-v2")
    assert out.result.ok and len(out.attempts) == 3 and pacer.slept == [60.0, 180.0]
    assert out.summary()["policy"]["id"] == "retry-v2"


def test_retry_v2_never_retries_an_http_error_and_respects_the_cap():
    assert len(client.rate_limited(_calls(FAIL["http_error"], OK), pacer=Pacer(), policy="retry-v2").attempts) == 1
    out = client.rate_limited(_calls(FAIL["timeout"], OK), pacer=Pacer(), policy="retry-v2", max_retries=0)
    assert len(out.attempts) == 1 and not out.result.ok


def test_the_policies_share_the_runners_retry_count():
    assert {p["max_rate_limit_retries"] for p in client.P1_RETRY_POLICIES.values()} == {er.P1_RATE_LIMIT_RETRIES}
    assert set(client.P1_RETRY_POLICIES) == set(er.RETRY_POLICIES)


def test_an_unknown_retry_policy_is_a_config_problem():
    config = er.load_config(er.CONFIG_DIR / "vss-baseline.json")
    config["pipeline"] = {**config["pipeline"], "retry_policy": "retry-v9"}
    assert any("retry_policy" in p for p in er.config_problems(config))


# --- host suspend ----------------------------------------------------------------------------------

def _clocks(suspended_s):
    wall, mono = iter([0.0, 100.0 + suspended_s] * 3), iter([0.0, 100.0] * 3)
    return {"wall": lambda: next(wall), "monotonic": lambda: next(mono)}


def test_a_failed_attempt_across_a_host_suspend_is_host_suspended_and_retried_under_v2():
    out = client.rate_limited(_calls(FAIL["timeout"], OK), pacer=Pacer(), policy="retry-v2", **_clocks(3600))
    assert out.attempts[0]["failure_kind"] == "host_suspended" and out.attempts[0]["host_suspended_s"] == 3600
    assert out.result.ok


def test_a_valid_output_across_a_suspend_is_kept_and_flagged():
    out = client.rate_limited(_calls(OK), pacer=Pacer(), policy="retry-v2", **_clocks(600))
    assert out.result.ok and out.attempts[0]["host_suspended_s"] == 600


def test_a_short_gap_is_not_a_suspend():
    out = client.rate_limited(_calls(FAIL["timeout"]), pacer=Pacer(), policy="retry-v1", **_clocks(5))
    assert out.result.failure_kind == "timeout" and out.attempts[0]["host_suspended_s"] is None


# --- recovery classification and merge -----------------------------------------------------------------

def _video(incident_id, repeat, outcome, error=""):
    return {"incident_id": incident_id, "repeat": repeat, "position": 0, "run_id": f"r{repeat}", "outcome": outcome,
            "p1_raw": {"ok": outcome == "scored", "failure_kind": outcome if outcome != "scored" else None,
                       "error": error}}


@pytest.mark.parametrize("video, expected", [
    (_video("A", 1, "scored"), None),
    (_video("A", 1, "contract_invalid"), None),
    (_video("A", 1, "timeout"), "timeout"),
    (_video("A", 1, "rate_limited"), "rate_limited"),
    (_video("A", 1, "host_suspended"), "host_suspended"),
    (_video("A", 1, "http_error", '{"detail": "P1 call returned HTTP 429: {...}"}'), "rate_limited"),
    (_video("A", 1, "http_error", '{"detail": "P1 call returned HTTP 524: <html>"}'), "timeout"),
    (_video("A", 1, "http_error", '{"detail": "boom"}'), None),
])
def test_only_infrastructure_failures_are_recoverable(video, expected):
    assert rec.failure_class(video) == expected


def _record(videos, **extra):
    return {"experiment_id": "x", "videos": videos, "complete": True, "reliability": {"attempted": len(videos)},
            **extra}


def test_the_plan_lists_failed_runs_and_leaves_genuine_errors():
    record = _record([_video("A", 1, "scored"), _video("A", 2, "timeout"), _video("B", 1, "http_error", "boom")])
    plan = rec.plan(record, results_path="p", results_sha256="h")
    assert [(r["incident_id"], r["repeat"]) for r in plan["runs"]] == [("A", 2)]
    assert [r["incident_id"] for r in plan["not_recoverable"]] == ["B"]


def test_merge_replaces_only_recovered_runs_and_keeps_the_original_reliability():
    original = _record([_video("A", 1, "scored"), _video("A", 2, "timeout")])
    recovery = _record([{**_video("A", 2, "scored"), "recovers": {"run_id": "r2"}}], protocol=rec.PROTOCOL,
                       recovers={"experiment_id": "x"})
    merged = rec.merge(original, recovery, recovery_path="rp", recovery_sha256="rh")
    assert merged["protocol"] == rec.MERGED_PROTOCOL and merged["reliability_original"] == {"attempted": 2}
    assert [v["outcome"] for v in merged["videos"]] == ["scored", "scored"]
    assert merged["videos"][1]["recovered_from"]["outcome"] == "timeout" and "recovered_from" not in merged["videos"][0]
    assert merged["reliability"]["no_model_output"] == 0 and original["videos"][1]["outcome"] == "timeout"


def test_run_stage_with_only_runs_the_listed_runs_and_links_them(tmp_path):
    gt = {"status": "frozen", "version": "v", "manifest": {"records_sha256": "g"}, "split": {"version": "split-v2"},
          "by_incident_id": {v: {"category": "Assault", "filename": f"{v}.mp4",
                                 "p1_shaped": {"entities": [], "instruments": [], "assets": []}} for v in ("A", "B")}}
    split = {"version": "split-v2", "dev": ["A", "B"], "test": []}
    original = er.load_config(er.CONFIG_DIR / "vss-baseline.json")
    plan = {"runs": [{"repeat": 2, "incident_id": "B", "position": 1, "run_id": "o", "outcome": "timeout",
                      "class": "timeout"}], "of": {"experiment_id": "vss-baseline"}}
    config = rec.recovery_config(original, plan, gt)
    assert config["pipeline"]["retry_policy"] == "retry-v2" and config["budget"]["max_p1_calls"] == 3
    seen = []

    def run_one(store, *, incident_id, model_run_id, p1_call, **_):
        seen.append(incident_id)
        p1_call("m", "u")
        return {"incident_id": incident_id, "outcome": "scored", "run_id": model_run_id, "judge_calls": 0,
                "judge_tokens": 0, "p1_raw": {"ok": True, "usage": {"total_tokens": 10},
                                              "rate_limit": {"attempt_count": 1, "attempts": [{}]}}}

    outcome = SimpleNamespace(result=SimpleNamespace(raw={}))
    out = er.run_stage([config], split=split, gt_index=gt,
                       store=SimpleNamespace(insert_model_run=lambda *a, **k: None),
                       video_source=lambda i: ("u", {}), call_factory_for=lambda c: (lambda *a, **k: (lambda *b: outcome)),
                       run_one=run_one, confirm_paid=True, results_root=tmp_path,
                       now=datetime(2026, 11, 2, tzinfo=UTC), log=lambda *_: None,
                       pricing={"provisional": False, "usd_per_million_tokens": {"default": 0.0}, "judge_model": "j",
                                "judge_tokens_per_call_estimate": 1},
                       only={config["experiment_id"]: {(2, "B")}},
                       recovery={config["experiment_id"]: rec.links(plan)})
    record = out["records"][0]
    assert seen == ["B"] and record["protocol"] == rec.PROTOCOL and record["videos"][0]["recovers"]["run_id"] == "o"


# --- calibration and re-matching -------------------------------------------------------------------------

class Embed:
    """A fake embedder: each text's vector is looked up by its first word."""

    VECTORS = {"human": [1.0, 0.0], "car": [0.0, 1.0], "truck": [0.6, 0.8]}

    def __call__(self, texts):
        return SimpleNamespace(ok=True, data=[self.VECTORS[t.split()[0]] for t in texts], error=None)


SHEET = {"blocks": [{"block_id": "B01", "incident_id": "X", "kind": "assets",
                     "predicted": [{"asset_id": "A1", "name": "car", "description": "red"},
                                   {"asset_id": "A2", "name": "truck", "description": "big"}],
                     "ground_truth": [{"asset_id": "A1", "name": "car", "description": "red car"}]}]}
LABELS = [{"block_id": "B01", "predicted_id": "A1", "gt_id": "A1", "label": "same"},
          {"block_id": "B01", "predicted_id": "A2", "gt_id": "A1", "label": "different"}]


def test_labels_must_cover_every_pair_once():
    assert mc.validate_labels(SHEET, LABELS) == []
    assert any("unlabelled" in p for p in mc.validate_labels(SHEET, LABELS[:1]))


def test_scoring_a_threshold_uses_the_hungarian_matcher():
    sims = mc.similarity_blocks(SHEET, embed=Embed())
    scored = mc.score_threshold(SHEET, LABELS, sims, 0.5)
    assert scored["by_kind"]["all"]["tp"] == 1 and scored["by_kind"]["all"]["fp"] == 0  # one-to-one: A2 unmatched


def test_the_selection_rule_breaks_near_ties_to_the_higher_threshold():
    table = [{"threshold": t, "by_kind": {"all": {"f1": f}}} for t, f in ((0.3, 0.80), (0.4, 0.795), (0.5, 0.6))]
    assert mc.select_threshold(table) == 0.4


def test_calibration_refuses_test_records():
    with pytest.raises(ValueError, match="dev results only"):
        mc.eligible_blocks([{"experiment_id": "t", "split": {"half": "test"}, "videos": []}])


def test_rematch_writes_a_new_versioned_record_and_keeps_the_original():
    video = {"outcome": "scored", "prediction": {"entities": [], "instruments": [], "assets": SHEET["blocks"][0]["predicted"]},
             "ground_truth": {"entities": [], "instruments": [], "assets": SHEET["blocks"][0]["ground_truth"]},
             "assets": {"matches": []}}
    record = {"videos": [video], "methodology": {"methodology_version": "evaluation-methodology-v1.1"}}
    out = item_rescore.rematch(record, threshold=0.5, methodology_version="evaluation-methodology-v1.2", source="s",
                               source_sha256="h", provisional=True, embed=Embed())
    assert out["videos"][0]["assets"]["counts"]["tp"] == 1 and video["assets"] == {"matches": []}
    assert out["methodology"]["match_threshold"] == 0.5 and out["rematched_from"]["methodology_version"].endswith("v1.1")


def test_v12_is_in_force_and_v11_is_kept():
    assert methodology.METHODOLOGY_VERSION == "evaluation-methodology-v1.2"
    assert methodology.MATCH_THRESHOLDS == {"evaluation-methodology-v1.1": 0.75, "evaluation-methodology-v1.2": 0.40}
    assert methodology.MATCH_CALIBRATION["evaluation-methodology-v1.2"]["human_validated"] is False


def test_d9_g3_refuses_mixed_methodologies_and_protocols(monkeypatch):
    base = {"videos": [], "plan": {"repeats": 2}, "model": "m", "ground_truth": {"records_sha256": "g"},
            "split": {"half": "dev"}, "methodology": {"methodology_version": "v1.2", "match_threshold": 0.3}}
    comparison = {"point": dict.fromkeys(es.EIGHT_SCORES), "ci95": dict.fromkeys(es.EIGHT_SCORES)}
    other = {**base, "methodology": {"methodology_version": "v1.1", "match_threshold": 0.75},
             "protocol": "original+recovery-v1"}
    monkeypatch.setattr(es, "valid_runs", lambda r: 0)  # G1 is not under test here
    problems = es.guardrails(base, other, comparison)
    assert "G3: different methodology" in problems and "G3: different protocol" in problems


# --- calibration v2 resolution and selection stability ------------------------------------------------

def _lab(label, **extra):
    return {"block_id": "B01", "predicted_id": "A1", "gt_id": "A1", "label": label, **extra}


@pytest.mark.parametrize("original, audit, uncertainty, expected, reviewed", [
    ("same", "same", "low", "same", False),
    ("ambiguous", "same", "medium", "same", False),
    ("ambiguous", "same", "high", "ambiguous", True),
    ("same", "different", "low", "ambiguous", True),
    ("different", "ambiguous", "high", "ambiguous", True),
])
def test_audit_resolution_follows_the_preregistered_rule(original, audit, uncertainty, expected, reviewed):
    labels, review = mc.resolve([_lab(original)], [_lab(audit, uncertainty=uncertainty)])
    assert labels[0]["label"] == expected and labels[0]["label_original"] == original
    assert bool(review) is reviewed


def test_selection_stability_and_the_conservative_fallback():
    # Two blocks that each favour a different threshold: unstable by construction.
    per_t = {0.2: {"B1": (5, 0, 0), "B2": (1, 4, 0)}, 0.5: {"B1": (3, 0, 2), "B2": (1, 0, 0)}}
    stability = mc.selection_stability(per_t, resamples=200, seed=1)
    assert set(stability["frequency"]) == {0.2, 0.5} and abs(sum(stability["frequency"].values()) - 1) < 1e-9
    chosen = mc.select_from_counts(per_t, ["B1", "B2"])
    assert chosen == 0.5  # pooled F1 0.80 against 0.75
    fallback = mc.conservative_choice(per_t, chosen, {"frequency": {0.2: 0.6, 0.5: 0.4}, "central90": [0.2, 0.5]})
    assert fallback["triggered"] and fallback["threshold"] == 0.5  # highest τ in range within 0.05 of the best F1
    stable = mc.conservative_choice(per_t, chosen, {"frequency": {chosen: 0.9}, "central90": [chosen, chosen]})
    assert stable == {"triggered": False, "threshold": chosen}


def test_large_blocks_are_drawn_without_scores_and_one_per_clip():
    blocks = [{"experiment_id": "e", "incident_id": f"C{i % 3}", "repeat": 1, "kind": k, "predicted": [], "ground_truth": []}
              for i, k in enumerate(["entities", "assets", "instruments"] * 3)]
    chosen = mc.sample_large([dict(b) for b in blocks], first_number=23, count=3)
    assert [b["block_id"] for b in chosen] == ["B23", "B24", "B25"] and len({b["incident_id"] for b in chosen}) == 3
    again = mc.sample_large([dict(b) for b in blocks], first_number=23, count=3)
    assert [(b["incident_id"], b["kind"]) for b in again] == [(b["incident_id"], b["kind"]) for b in chosen]


# --- Stage 2: caps, resume, host guard --------------------------------------------------------------

def _gt_many(n):
    return {"status": "frozen", "version": "v", "manifest": {"records_sha256": "g"}, "split": {"version": "split-v2"},
            "by_incident_id": {f"V{i:02d}": {"category": "Assault", "filename": f"V{i:02d}.mp4", "p1_shaped": {
                "entities": [{}], "instruments": [], "assets": [{}]}} for i in range(n)}}


def _stage(configs, gt, tmp_path, *, attempts=1, fail_after=None, resume=None, seen=None):
    calls = {"n": 0}

    def run_one(store, *, incident_id, model_run_id, p1_call, **_):
        calls["n"] += 1
        if fail_after is not None and calls["n"] > fail_after:
            raise KeyboardInterrupt  # the laptop dies mid-stage
        if seen is not None:
            seen.append(incident_id)
        p1_call("m", "u")
        rows = [{"failure_kind": "timeout"}] * (attempts - 1) + [{"failure_kind": None}]
        return {"incident_id": incident_id, "outcome": "scored", "run_id": model_run_id, "judge_calls": 0,
                "judge_tokens": 0, "p1_raw": {"ok": True, "usage": {"total_tokens": 9500},
                                              "rate_limit": {"attempt_count": attempts, "attempts": rows}}}

    outcome = SimpleNamespace(result=SimpleNamespace(raw={}))
    split = {"version": "split-v2", "dev": sorted(gt["by_incident_id"]), "test": []}
    return er.run_stage(configs, split=split, gt_index=gt, store=SimpleNamespace(insert_model_run=lambda *a, **k: None),
                        video_source=lambda i: ("u", {}),
                        call_factory_for=lambda c: (lambda *a, **k: (lambda *b: outcome)), run_one=run_one,
                        confirm_paid=True, results_root=tmp_path, now=datetime(2026, 11, 3, tzinfo=UTC),
                        log=lambda *_: None, resume=resume,
                        pricing={"provisional": False, "usd_per_million_tokens": {"default": 0.0}, "judge_model": "j",
                                 "judge_tokens_per_call_estimate": 1})


def _s2_configs():
    return [er.load_config(p) for p in sorted(er.CONFIG_DIR.glob("s2-*.json"))]


def test_stage2_caps_survive_the_worst_case_of_three_unmetered_attempts_per_run(tmp_path):
    """Every Stage 2a config completes all 50 runs even if every run needs 3 attempts and the first two report no usage."""
    configs = _s2_configs()
    assert len(configs) == 8 and all(c["pipeline"]["retry_policy"] == "retry-v2" for c in configs)
    out = _stage(configs, _gt_many(25), tmp_path, attempts=3)
    assert out["stopped"] is None and all(r["usage"]["p1_calls"] == 50 for r in out["records"])
    assert all(r["usage"]["p1_attempts"] == 150 for r in out["records"])


def test_an_interrupted_stage_resumes_where_it_stopped(tmp_path):
    configs = _s2_configs()[:2]
    gt = _gt_many(3)
    with pytest.raises(KeyboardInterrupt):
        _stage(configs, gt, tmp_path, fail_after=5)
    stage_dir = next((tmp_path / "stages").iterdir())
    seen = []
    out = _stage(configs, gt, tmp_path, resume=stage_dir, seen=seen)
    assert out["stopped"] is None and len(seen) == 12 - 5
    assert all(len(r["videos"]) == 6 and r["resumed"][0]["after_video_runs"] == 5 for r in out["records"])
    with pytest.raises(er.ExperimentRefused, match="already wrote"):
        _stage(configs, gt, tmp_path, resume=stage_dir)


def test_paid_runs_on_wsl_need_the_wake_request(monkeypatch):
    import eval_experiment

    args = SimpleNamespace(allow_sleep=False)
    monkeypatch.setenv("KEEP_AWAKE_ACTIVE", "1")
    assert eval_experiment.host_guard(args) is None
    monkeypatch.delenv("KEEP_AWAKE_ACTIVE")
    monkeypatch.setattr(eval_experiment.Path, "read_text", lambda self: "Linux 6.6 microsoft-standard-WSL2")
    assert "keep-awake" in eval_experiment.host_guard(args)
    assert eval_experiment.host_guard(SimpleNamespace(allow_sleep=True)) is None


def test_the_matcher_defaults_to_the_methodology_threshold():
    import matching

    just_below = [[0.399]]
    assert matching.solve_assignment(just_below) == []
    assert len(matching.solve_assignment([[0.40]])) == 1


def test_a_recovery_beyond_the_hard_limit_is_refused():
    plan = {"runs": [{"repeat": 1, "incident_id": f"V{i:02d}", "position": i, "run_id": "r", "outcome": "timeout",
                      "class": "timeout"} for i in range(rec.MAX_RECOVERED_RUNS + 1)], "of": {}}
    original = er.load_config(er.CONFIG_DIR / "s2-vss-baseline.json")
    with pytest.raises(rec.RecoveryRefused, match="persistent outage|recovery limit"):
        rec.recovery_config(original, plan, _gt_many(25))
    cfg = rec.recovery_config(original, {**plan, "runs": plan["runs"][:15]}, _gt_many(25))
    assert cfg["budget"]["max_p1_calls"] == 45 and cfg["budget"]["max_p1_tokens"] == 45 * er.P1_TOKENS_CEILING


def _outage_stage(configs, gt, tmp_path, *, no_output_from=None, clock=None, session_seconds=None, resume=None,
                  seen=None):
    calls = {"n": 0}

    def run_one(store, *, incident_id, model_run_id, p1_call, **_):
        calls["n"] += 1
        if seen is not None:
            seen.append(incident_id)
        p1_call("m", "u")
        down = no_output_from is not None and calls["n"] >= no_output_from
        return {"incident_id": incident_id, "outcome": "timeout" if down else "scored", "run_id": model_run_id,
                "judge_calls": 0, "judge_tokens": 0,
                "p1_raw": {"ok": not down, "usage": {} if down else {"total_tokens": 9500},
                           "rate_limit": {"attempt_count": 3 if down else 1,
                                          "attempts": [{"failure_kind": "timeout"}] * 3 if down else [{}]}}}

    outcome = SimpleNamespace(result=SimpleNamespace(raw={}))
    split = {"version": "split-v2", "dev": sorted(gt["by_incident_id"]), "test": []}
    kwargs = {"clock": clock} if clock else {}
    return er.run_stage(configs, split=split, gt_index=gt, store=SimpleNamespace(insert_model_run=lambda *a, **k: None),
                        video_source=lambda i: ("u", {}),
                        call_factory_for=lambda c: (lambda *a, **k: (lambda *b: outcome)), run_one=run_one,
                        confirm_paid=True, results_root=tmp_path, now=datetime(2026, 11, 4, tzinfo=UTC),
                        log=lambda *_: None, resume=resume, session_seconds=session_seconds,
                        pricing={"provisional": False, "usd_per_million_tokens": {"default": 0.0}, "judge_model": "j",
                                 "judge_tokens_per_call_estimate": 1}, **kwargs)


def test_an_outage_pauses_after_four_failed_runs_without_spending_more(tmp_path):
    configs = _s2_configs()[:2]
    out = _outage_stage(configs, _gt_many(5), tmp_path, no_output_from=3)
    assert out["paused"]["reason"].startswith(f"{er.OUTAGE_PAUSE_RUNS} consecutive") and out["results_files"] == []
    assert sum(len(r["videos"]) for r in out["records"]) == 2 + er.OUTAGE_PAUSE_RUNS
    seen = []
    resumed = _outage_stage(configs, _gt_many(5), tmp_path, resume=Path(out["stage_dir"]), seen=seen)
    assert resumed["paused"] is None if "paused" in resumed else True
    assert resumed["stopped"] is None and len(seen) == 20 - 6
    assert all(len(r["videos"]) == 10 for r in resumed["records"])


def test_the_session_limit_pauses_between_video_runs(tmp_path):
    ticks = iter(range(0, 100000, 1000))
    out = _outage_stage(_s2_configs()[:2], _gt_many(5), tmp_path, clock=lambda: next(ticks), session_seconds=3500)
    assert out["paused"]["reason"].startswith("session time limit") and out["paused"]["done"] == 3
