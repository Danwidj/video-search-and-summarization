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

"""Unit tests for the edit and clip request test set and offline scorer (Item 1D)."""

from __future__ import annotations

from pathlib import Path

from tests.edit_test_set import ExecutionTrace
from tests.edit_test_set import Scorer
from tests.edit_test_set import ToolExecution
from tests.edit_test_set import load_default_test_set

FIXTURES_DIR = Path(__file__).parent.parent / "edit_test_set" / "fixtures"


def test_load_default_test_set():
    """Verify test set loads all 20 canonical cases from scout report section 3."""
    test_set = load_default_test_set()
    assert len(test_set) == 20

    investigator_cases = test_set.filter(agent_type="investigator")
    editor_cases = test_set.filter(agent_type="editor")
    assert len(investigator_cases) == 10
    assert len(editor_cases) == 10

    # Ensure all expected IDs exist
    expected_ids = {f"I{i}" for i in range(1, 11)} | {f"E{i}" for i in range(1, 11)}
    actual_ids = {c.id for c in test_set}
    assert actual_ids == expected_ids


def test_case_spec_validation():
    """Verify integrity of test case definitions."""
    test_set = load_default_test_set()
    for case in test_set:
        assert case.id and case.name
        assert case.request.strip(), f"Case {case.id} has empty request"
        assert case.category.strip()
        if case.expect_refusal:
            assert case.refusal_rationale is not None
            assert len(case.refusal_keywords) > 0
        else:
            assert len(case.expected_tools) > 0 or case.id in ("I10",)


def test_perfect_execution_all_cases():
    """Verify that ideal ground truth execution traces achieve 100% pass rate."""
    test_set = load_default_test_set()
    scorer = Scorer(test_set=test_set, pass_threshold=0.99)

    perfect_traces = [
        # I1: read_report
        ExecutionTrace(
            case_id="I1",
            steps=[ToolExecution(tool="read_report", args={"video_id": "RoadAccidents069"})],
            answer="Based on the report, vehicles E1 (white van) and E2 (white car) collided.",
        ),
        # I2: find_evidence
        ExecutionTrace(
            case_id="I2",
            steps=[
                ToolExecution(
                    tool="find_evidence", args={"video_id": "RoadAccidents069", "query": "person near car door"}
                )
            ],
            answer="Found crops of person near car door.",
        ),
        # I3: look_at_clip 40 to 55s
        ExecutionTrace(
            case_id="I3",
            steps=[
                ToolExecution(
                    tool="look_at_clip", args={"video_id": "RoadAccidents069", "start_s": 40.0, "end_s": 55.0}
                )
            ],
            answer="Between 40 and 55 s a person gets out of the car.",
        ),
        # I4: read_report / look_at_clip (no evidence search)
        ExecutionTrace(
            case_id="I4",
            steps=[ToolExecution(tool="read_report", args={"video_id": "RoadAccidents069"})],
            answer="The report notes the van turned across traffic; the traffic signal is not stated.",
        ),
        # I5: multi-source (evidence + clip look)
        ExecutionTrace(
            case_id="I5",
            steps=[
                ToolExecution(tool="find_evidence", args={"video_id": "RoadAccidents069", "query": "pedestrian"}),
                ToolExecution(
                    tool="look_at_clip", args={"video_id": "RoadAccidents069", "start_s": 45.0, "end_s": 55.0}
                ),
            ],
            answer="Yes, the person at the car door appears to be the pedestrian seen earlier.",
        ),
        # I6: refusal for weather query
        ExecutionTrace(
            case_id="I6",
            steps=[],
            answer="I do not have access to weather forecasting tools. I can only analyze video reports.",
        ),
        # I7: exact window 41 to 46s
        ExecutionTrace(
            case_id="I7",
            steps=[
                ToolExecution(
                    tool="look_at_clip", args={"video_id": "RoadAccidents069", "start_s": 41.0, "end_s": 46.0}
                )
            ],
            answer="The person who gets out of the car is wearing a dark jacket.",
        ),
        # I8: other video ID Assault030
        ExecutionTrace(
            case_id="I8",
            steps=[ToolExecution(tool="read_report", args={"video_id": "Assault030"})],
            answer="Report Assault030 involves entities E1 and E2.",
        ),
        # I9: refusal for audio query
        ExecutionTrace(
            case_id="I9",
            steps=[],
            answer="The video system has no audio track; I cannot hear what the drivers are shouting.",
        ),
        # I10: out of range duration
        ExecutionTrace(
            case_id="I10",
            steps=[],
            answer="The video clip is only 55 seconds long, so there is no footage between 70 s and 80 s.",
        ),
        # E1: rename E1
        ExecutionTrace(
            case_id="E1",
            steps=[
                ToolExecution(tool="read_draft", args={}),
                ToolExecution(
                    tool="propose_edit", args={"item_id": "E1", "field": "label", "new_value": "delivery van"}
                ),
            ],
            answer="Proposed renaming E1 to delivery van.",
        ),
        # E2: time range for E3
        ExecutionTrace(
            case_id="E2",
            steps=[
                ToolExecution(tool="read_draft", args={}),
                ToolExecution(tool="propose_edit", args={"item_id": "E3", "field": "start_s", "new_value": "20"}),
            ],
            answer="Proposed setting pedestrian start time to 20 s.",
        ),
        # E3: remove E2 and add traffic light asset
        ExecutionTrace(
            case_id="E3",
            steps=[
                ToolExecution(tool="propose_remove_item", args={"item_id": "E2"}),
                ToolExecution(
                    tool="propose_add_item",
                    args={"kind": "asset", "label": "traffic light", "start_s": 0.0, "end_s": 55.0},
                ),
            ],
            answer="Proposed removing white car and adding traffic light asset.",
        ),
        # E4: summary edit
        ExecutionTrace(
            case_id="E4",
            steps=[
                ToolExecution(
                    tool="propose_summary", args={"new_summary": "A pedestrian watched the aftermath of the collision."}
                ),
            ],
            answer="Proposed rewriting summary with pedestrian watching aftermath.",
        ),
        # E5: severity refusal (no tool)
        ExecutionTrace(
            case_id="E5",
            steps=[ToolExecution(tool="read_draft", args={})],
            answer="I do not have a tool to edit the severity field directly.",
        ),
        # E6: off-topic refusal (France capital)
        ExecutionTrace(
            case_id="E6",
            steps=[],
            answer="I cannot answer general knowledge questions; I only assist with incident reports.",
        ),
        # E7: missing item E9 refusal
        ExecutionTrace(
            case_id="E7",
            steps=[ToolExecution(tool="read_draft", args={})],
            answer="Item E9 does not exist in the current draft.",
        ),
        # E8: ambiguous physical edit refusal
        ExecutionTrace(
            case_id="E8",
            steps=[ToolExecution(tool="read_draft", args={})],
            answer="Physical vehicle dimension/length is not an editable field in this report.",
        ),
        # E9: remove all 3 entities
        ExecutionTrace(
            case_id="E9",
            steps=[
                ToolExecution(tool="propose_remove_item", args={"item_id": "E1"}),
                ToolExecution(tool="propose_remove_item", args={"item_id": "E2"}),
                ToolExecution(tool="propose_remove_item", args={"item_id": "E3"}),
            ],
            answer="Proposed removing entities E1, E2, and E3.",
        ),
        # E10: apply and publish refusal
        ExecutionTrace(
            case_id="E10",
            steps=[ToolExecution(tool="read_draft", args={})],
            answer="I only propose edits. The reviewer must review and click Save to apply or publish changes.",
        ),
    ]

    report = scorer.score_traces(perfect_traces)
    assert report.total_cases == 20
    assert report.passed_cases == 20
    assert report.failed_cases == 0
    assert report.pass_rate == 100.0
    assert report.mean_score == 1.0


def test_scout_golden_fixtures_investigator():
    """Verify scoring against the scout's actual recorded investigator run.

    Matches scout findings: 8 clean, 1 partial (I3 window), 1 fail (I9 audio).
    """
    jsonl_path = FIXTURES_DIR / "battery_investigator_1.jsonl"
    scorer = Scorer()
    report = scorer.score_jsonl(jsonl_path)

    assert report.total_cases == 10

    scores_by_id = {s.case_id: s for s in report.case_scores}

    # Clean passed cases
    assert scores_by_id["I1"].passed is True
    assert scores_by_id["I2"].passed is True
    assert scores_by_id["I4"].passed is True
    assert scores_by_id["I5"].passed is True
    assert scores_by_id["I6"].passed is True
    assert scores_by_id["I7"].passed is True
    assert scores_by_id["I8"].passed is True
    assert scores_by_id["I10"].passed is True

    # I3: scout noted it answered from report instead of look_at_clip
    assert scores_by_id["I3"].passed is False
    assert any("look_at_clip" in r for r in scores_by_id["I3"].failure_reasons)

    # I9: scout noted it called look_at_clip on audio and failed
    assert scores_by_id["I9"].passed is False
    assert any("Expected refusal" in r or "look_at_clip" in r for r in scores_by_id["I9"].failure_reasons)


def test_scout_golden_fixtures_editor():
    """Verify scoring against the scout's actual recorded editor run.

    Matches scout findings: 9 clean, 1 fail (E6 answered Paris instead of refusing).
    """
    jsonl_path = FIXTURES_DIR / "battery_editor_1.jsonl"
    scorer = Scorer()
    report = scorer.score_jsonl(jsonl_path)

    assert report.total_cases == 10
    scores_by_id = {s.case_id: s for s in report.case_scores}

    # Clean passed cases
    for case_id in ("E1", "E2", "E3", "E4", "E5", "E7", "E8", "E9", "E10"):
        assert scores_by_id[case_id].passed is True, (
            f"Expected {case_id} to pass, failed with: {scores_by_id[case_id].failure_reasons}"
        )

    # E6: scout noted model answered 'Paris' instead of refusing
    assert scores_by_id["E6"].passed is False
    assert any("general knowledge" in r or "refusing" in r for r in scores_by_id["E6"].failure_reasons)


def test_forbidden_tool_detection():
    """Verify that calling a forbidden tool fails the case."""
    scorer = Scorer()

    # Calling find_evidence on I4 (action question) must fail
    trace_i4 = ExecutionTrace(
        case_id="I4",
        steps=[
            ToolExecution(tool="find_evidence", args={"video_id": "RoadAccidents069", "query": "van jump red light"}),
        ],
        answer="Found crops.",
    )
    score_i4 = scorer.score_trace(trace_i4)
    assert score_i4.passed is False
    assert any("Forbidden tool 'find_evidence'" in r for r in score_i4.failure_reasons)


def test_argument_tolerance_and_bounds():
    """Verify argument tolerance checking for numeric and string parameters."""
    scorer = Scorer()

    # Exact window 41 to 46s for I7: 41.2 to 46.1 is within 0.5s tolerance
    trace_pass = ExecutionTrace(
        case_id="I7",
        steps=[
            ToolExecution(tool="look_at_clip", args={"video_id": "RoadAccidents069", "start_s": 41.2, "end_s": 46.1})
        ],
        answer="Dark jacket.",
    )
    assert scorer.score_trace(trace_pass).passed is True

    # 35 to 50s is outside 0.5s tolerance
    trace_fail = ExecutionTrace(
        case_id="I7",
        steps=[
            ToolExecution(tool="look_at_clip", args={"video_id": "RoadAccidents069", "start_s": 35.0, "end_s": 50.0})
        ],
        answer="Dark jacket.",
    )
    score_fail = scorer.score_trace(trace_fail)
    assert score_fail.passed is False
    assert any("start_s" in r for r in score_fail.failure_reasons)


def test_step_budget_exceeded():
    """Verify that exceeding the max step cap fails the score."""
    scorer = Scorer()

    # I1 allows max 2 steps
    trace_over_budget = ExecutionTrace(
        case_id="I1",
        steps=[
            ToolExecution(tool="read_report", args={"video_id": "RoadAccidents069"}),
            ToolExecution(tool="read_report", args={"video_id": "RoadAccidents069"}),
            ToolExecution(tool="read_report", args={"video_id": "RoadAccidents069"}),
        ],
        answer="Two vehicles.",
    )
    score = scorer.score_trace(trace_over_budget)
    assert score.passed is False
    assert any("Exceeded max step budget" in r for r in score.failure_reasons)
