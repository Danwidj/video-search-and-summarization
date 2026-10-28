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

"""AI-assisted adjudication (gt-adjudication-v1.0): validation, application, provenance and the freeze gate."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ground_truth_correction as gtc  # noqa: E402
import ground_truth_freeze as gtf  # noqa: E402
import gt_candidate_build  # noqa: E402
import review_backup  # noqa: E402
from test_ground_truth_correction import _changes, _first, _proposal, setup  # noqa: E402, F401

PROMPT_SHA = hashlib.sha256(gt_candidate_build.ADJUDICATION_PROMPT_PATH.read_bytes()).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    """A close-up image with its sidecar (tile times 10.0 and 10.5)."""
    path = tmp_path / "eval_data" / "gt_adjudication" / "X" / "burst.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"jpg")
    path.with_suffix(".json").write_text(json.dumps({"times": [10.0, 10.5]}))
    return tmp_path, "eval_data/gt_adjudication/X/burst.jpg"


def _record(change, decision="ACCEPT", final_value=None, impact="medium", file="eval_data/gt_adjudication/X/burst.jpg",
            **overrides):
    record = {"change_id": change.change_id, "incident_id": change.incident_id, "record_id": str(change.record_id),
              "field": change.field, "rule": change.rule, "decision": decision, "final_value": final_value,
              "impact": impact, "blind_assessment": "seen", "justification": "because",
              "evidence": [{"file": file, "t": 10.0, "observation": "x"}], "video_verified": True, "uncertain": False,
              "agrees_with_ai": decision == "ACCEPT", "adjudicator": {"kind": "ai", "model": "m"},
              "adjudication_prompt": "gt-adjudication-v1.0", "adjudication_prompt_sha256": PROMPT_SHA,
              "guidelines": "annotation-guidelines-v1.0", "provenance": "AI-assisted, not human-reviewed"}
    record.update(overrides)
    return record


def _validate(record, change, proposal, base):
    return gtc.validate_adjudication(record, change, proposal, base=base, prompt_sha256=PROMPT_SHA)


def test_a_valid_accept_of_a_proposal(setup, evidence):  # noqa: F811
    base, _ = evidence
    _, _, changes = _changes(*setup[:2])
    r25 = _first(changes, "R25")
    proposal = _proposal(r25)
    assert _validate(_record(r25, final_value=proposal["proposed_value"]), r25, proposal, base) == []


@pytest.mark.parametrize("overrides, problem", [
    ({"decision": "MAYBE"}, "decision"),
    ({"video_verified": False}, "video-verified"),
    ({"evidence": []}, "no evidence"),
    ({"evidence": [{"file": "eval_data/gt_adjudication/X/burst.jpg", "t": 3.0}]}, "not a tile"),
    ({"evidence": [{"file": "eval_data/nope.jpg", "t": 10.0}]}, "does not exist"),
    ({"provenance": "human"}, "provenance"),
    ({"adjudication_prompt_sha256": "0" * 64}, "prompt"),
    ({"justification": ""}, "justification"),
    ({"impact": "huge"}, "impact"),
    ({"final_value": "something else"}, "unchanged"),
])
def test_invalid_adjudications_are_reported(setup, evidence, overrides, problem):  # noqa: F811
    base, _ = evidence
    _, _, changes = _changes(*setup[:2])
    r25 = _first(changes, "R25")
    proposal = _proposal(r25)
    record = {**_record(r25, final_value=proposal["proposed_value"]), **overrides}
    assert any(problem in p for p in _validate(record, r25, proposal, base))


def test_decision_rules_against_the_earlier_proposal(setup, evidence):  # noqa: F811
    base, _ = evidence
    _, _, changes = _changes(*setup[:2])
    r25, r23 = _first(changes, "R25"), _first(changes, "R23")
    keep = _proposal(r25, decision="keep_original", proposed_value=None)
    assert any("REJECT of a keep_original" in p for p in _validate(_record(r25, "REJECT"), r25, keep, base))
    unsure = _proposal(r25, decision="uncertain", proposed_value=None)
    assert any("ACCEPT of an uncertain" in p for p in _validate(_record(r25, "ACCEPT"), r25, unsure, base))
    assert any("1-5" in p for p in _validate(_record(r23, "MODIFY", final_value=7, impact="high"), r23, None, base))
    assert any("close-up" in p for p in _validate(_record(r23, "MODIFY", final_value=2, impact="high",
                                                          file="eval_data/gt_frames/X/window-1.jpg"), r23, None, base))
    assert any("null" in p for p in _validate(_record(r25, "UNRESOLVED", final_value="x"), r25, None, base))


def _candidate(setup, tmp_path, records):  # noqa: F811
    source, manifest, prior = setup
    proposals = tmp_path / "ai-proposals-v0.2.jsonl"
    _, _, changes = _changes(source, manifest)
    r25 = _first(changes, "R25")
    proposals.write_text(json.dumps(_proposal(r25)) + "\n")
    adjudication = tmp_path / "adjudication.jsonl"
    adjudication.write_text("".join(json.dumps(r) + "\n" for r in records))
    frames = tmp_path / "frames"
    (frames / r25.incident_id).mkdir(parents=True)
    (frames / r25.incident_id / "frames.json").write_text(json.dumps(
        {"sheets": [{"file": "window-1.jpg", "times": [0.0, 1.0, 2.0, 3.0], "sha256": "a" * 64}]}))
    return gt_candidate_build.build(source, manifest, prior, proposals, tmp_path / "out", "v0.3", frames_dir=frames,
                                    adjudication_path=adjudication), adjudication, proposals


def test_adjudicated_candidate_is_separate_labelled_and_never_human(setup, tmp_path, evidence, monkeypatch):  # noqa: F811
    base, _ = evidence
    monkeypatch.setattr(gt_candidate_build, "EVAL_DIR", base)
    source, manifest, prior = setup
    _, _, changes = _changes(source, manifest)
    r25, r23 = _first(changes, "R25"), _first(changes, "R23")
    proposal = _proposal(r25)
    records = [_record(r25, final_value=proposal["proposed_value"]),
               _record(r23, "MODIFY", final_value=2, impact="high")]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, prior)}
    result, _, _ = _candidate(setup, tmp_path, records)
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, prior)} == before
    assert result["output_name"] == "Ground Truth AI-Adjudicated Candidate v0.3.xlsx"
    assert result["statuses"]["AI-Accepted"] == 1 and result["statuses"]["AI-Modified"] == 1
    assert result["adjudication"]["decisions"] == {"ACCEPT": 1, "MODIFY": 1}
    assert result["adjudication"]["scoring_eligibility"]["severity_or_threat_changed"] == [r23.change_id]
    wb = openpyxl.load_workbook(tmp_path / "out" / result["output_name"])
    header = [c.value for c in wb["Change Log"][1]]
    rows = {r[0]: dict(zip(header, r)) for r in wb["Change Log"].iter_rows(min_row=2, values_only=True)}
    assert rows[r23.change_id]["Reviewer"] is None  # never a fabricated human approval
    assert rows[r23.change_id]["Adjudication provenance"] == "AI-assisted, not human-reviewed"
    assert rows[r23.change_id]["Applied in candidate"] == "yes"
    assert review_backup.review_state(tmp_path / "out" / result["output_name"])["decisions"] == 0


def test_an_invalid_adjudication_is_never_applied(setup, tmp_path, evidence, monkeypatch):  # noqa: F811
    base, _ = evidence
    monkeypatch.setattr(gt_candidate_build, "EVAL_DIR", base)
    _, _, changes = _changes(*setup[:2])
    r23 = _first(changes, "R23")
    result, _, _ = _candidate(setup, tmp_path, [_record(r23, "MODIFY", final_value=2, impact="high",
                                                        video_verified=False)])
    assert result["statuses"].get("AI-Modified") is None and any("invalid" in p for p in result["problems"])


def test_unresolved_entries_block_the_freeze_until_the_owner_decides():
    entry = gtc.Entry("CL-1", "R22", "needs_video_review", "gt_incidents", 2, "A", "A", "(review flag)", "x", None,
                      status="AI-Unresolved")
    assert any("AI-unresolved" in i for i in gtf.blocking_issues([entry], [], []))
    assert gtf.blocking_issues([entry], [], [], unresolved_keep_original=["CL-1"]) == []
    assert any("not AI-unresolved" in i for i in gtf.blocking_issues([entry], [], [],
                                                                      unresolved_keep_original=["CL-1", "CL-9"]))


def test_a_human_decision_overrides_the_ai_adjudication(setup, evidence):  # noqa: F811
    base, _ = evidence
    values, manifest, changes = _changes(*setup[:2])
    r23 = _first(changes, "R23")
    judged = {r23.change_id: {**_record(r23, "MODIFY", final_value=2, impact="high"), "_problems": []}}
    entries = gtc.resolve(changes, prior={r23.change_id: {"Review status": "Rejected"}}, prior_name="p",
                          verification={}, proposals={}, proposal_problems={}, adjudication=judged)
    entry = next(e for e in entries if e.change_id == r23.change_id)
    assert entry.status == "Rejected" and not entry.applied
