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

"""Scorer for edit and clip test cases that runs completely without hosted models.

Evaluates:
- Tool selection accuracy (precision, recall, F1, forbidden tools)
- Argument accuracy (exact match, numerical tolerance, regex patterns)
- Refusal handling (out-of-scope, unanswerable audio, invalid IDs, ambiguous requests)
- Step budgets and caps
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any

from pydantic import BaseModel
from pydantic import Field

if TYPE_CHECKING:
    from pathlib import Path

from .cases import ExpectedTool
from .cases import TestSet
from .cases import load_default_test_set
from .cases import normalize_tool_name


class ToolExecution(BaseModel):
    """Recorded single tool call during agent execution."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    ms: float | None = None


class ExecutionTrace(BaseModel):
    """Agent execution trace for a single test case."""

    case_id: str
    steps: list[ToolExecution] = Field(default_factory=list)
    status: str = "ok"
    answer: str = ""
    wall_ms: float | None = None
    llm_calls: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionTrace:
        """Parse execution trace from various JSON/JSONL log formats."""
        # 1. Resolve case_id (handles 'I1', 'I1 report-only', 'case': 'I1', 'case_id': 'I1')
        raw_case = data.get("case_id") or data.get("case") or data.get("id") or ""
        case_id = raw_case.split()[0].strip() if raw_case else ""

        # 2. Extract steps
        raw_steps = data.get("steps") or data.get("tool_steps") or data.get("proposals") or []
        steps: list[ToolExecution] = []
        for s in raw_steps:
            if isinstance(s, (list, tuple)):
                # Tuple format: [tool_name, args_dict, ok_bool]
                t_name = str(s[0]) if len(s) > 0 else ""
                t_args = s[1] if len(s) > 1 and isinstance(s[1], dict) else {}
                t_ok = bool(s[2]) if len(s) > 2 else True
                steps.append(ToolExecution(tool=t_name, args=t_args, ok=t_ok))
            elif isinstance(s, dict):
                t_name = s.get("tool") or s.get("name") or ""
                t_args = s.get("args") or s.get("arguments") or {}
                t_ok = s.get("ok", True)
                t_ms = s.get("ms")
                steps.append(ToolExecution(tool=t_name, args=t_args, ok=t_ok, ms=t_ms))

        status = str(data.get("status") or "ok")
        answer = str(data.get("answer") or data.get("reply") or "")
        wall_ms = data.get("wall_ms")
        llm_calls = data.get("llm_calls")

        return cls(
            case_id=case_id,
            steps=steps,
            status=status,
            answer=answer,
            wall_ms=wall_ms,
            llm_calls=llm_calls,
        )


class CaseScore(BaseModel):
    """Evaluation result and detailed scores for a single test case."""

    case_id: str
    case_name: str
    agent_type: str
    category: str
    tool_selection_score: float = Field(ge=0.0, le=1.0)
    argument_score: float = Field(ge=0.0, le=1.0)
    refusal_score: float = Field(ge=0.0, le=1.0)
    budget_score: float = Field(ge=0.0, le=1.0)
    total_score: float = Field(ge=0.0, le=1.0)
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)


class ScoreReport(BaseModel):
    """Aggregate evaluation report for a test suite run."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    mean_score: float
    case_scores: list[CaseScore]

    def summary_table(self) -> str:
        """Format a clear Markdown summary table of the evaluation."""
        lines = [
            f"# Test Set Evaluation Report (Pass Rate: {self.pass_rate:.1f}%)",
            "",
            f"**Total Cases:** {self.total_cases} | **Passed:** {self.passed_cases} | "
            f"**Failed:** {self.failed_cases} | **Mean Score:** {self.mean_score:.3f}",
            "",
            "| Case ID | Agent | Category | Pass | Score | Tool | Args | Refusal | Failure Details |",
            "|---|---|---|:---:|:---:|:---:|:---:|:---:|---|",
        ]
        for s in self.case_scores:
            status_str = "PASS" if s.passed else "FAIL"
            reasons_str = "; ".join(s.failure_reasons) if s.failure_reasons else "-"
            # Truncate long reasons for clean table
            if len(reasons_str) > 60:
                reasons_str = reasons_str[:57] + "..."
            lines.append(
                f"| {s.case_id} | {s.agent_type[:4]} | {s.category} | {status_str} | "
                f"{s.total_score:.2f} | {s.tool_selection_score:.2f} | {s.argument_score:.2f} | "
                f"{s.refusal_score:.2f} | {reasons_str} |"
            )
        return "\n".join(lines)


class Scorer:
    """Offline evaluator for edit and clip test cases."""

    def __init__(
        self,
        test_set: TestSet | None = None,
        pass_threshold: float = 0.99,
    ) -> None:
        self.test_set = test_set or load_default_test_set()
        self.pass_threshold = pass_threshold

    def score_trace(self, trace: ExecutionTrace) -> CaseScore:
        """Score an execution trace against the corresponding test case."""
        case = self.test_set.get(trace.case_id)
        if case is None:
            return CaseScore(
                case_id=trace.case_id,
                case_name=f"Unknown case {trace.case_id}",
                agent_type="unknown",
                category="unknown",
                tool_selection_score=0.0,
                argument_score=0.0,
                refusal_score=0.0,
                budget_score=0.0,
                total_score=0.0,
                passed=False,
                failure_reasons=[f"Case id '{trace.case_id}' not found in test set"],
            )

        failures: list[str] = []

        # 1. Budget check
        actual_step_count = len(trace.steps)
        if actual_step_count > case.max_steps:
            budget_score = 0.0
            failures.append(f"Exceeded max step budget: {actual_step_count} > {case.max_steps}")
        else:
            budget_score = 1.0

        # 2. Forbidden tools check
        forbidden_clean = [normalize_tool_name(t) for t in case.forbidden_tools]
        for step in trace.steps:
            norm_tool = normalize_tool_name(step.tool)
            if norm_tool in forbidden_clean:
                failures.append(f"Forbidden tool '{step.tool}' was invoked")

        # 3. Filter steps (remove optional intermediate steps like read_draft or read_report)
        optional_clean = [normalize_tool_name(t) for t in case.optional_tools]
        action_steps = [s for s in trace.steps if normalize_tool_name(s.tool) not in optional_clean]

        # 4. Refusal Evaluation
        refusal_score = 1.0
        if case.expect_refusal:
            # When refusal is expected, no action tools should be called
            if action_steps:
                action_names = [s.tool for s in action_steps]
                failures.append(f"Expected refusal, but agent called tools: {action_names}")
                refusal_score = 0.0
            else:
                # Check for refusal indicators in answer text
                answer_lower = trace.answer.lower()

                # Specific failure detection: e.g. E6 capital of France answering 'Paris'
                if (
                    case.id == "E6"
                    and "paris" in answer_lower
                    and not any(k in answer_lower for k in ("cannot", "unable", "only", "out of scope"))
                ):
                    failures.append("Agent answered general knowledge query instead of refusing")
                    refusal_score = 0.0
                elif case.refusal_keywords:
                    # Check if at least one refusal keyword appears in answer
                    matched_kw = [k for k in case.refusal_keywords if k.lower() in answer_lower]
                    if not matched_kw and not trace.status.startswith("refused"):
                        # Soft penalty if no standard keyword matched
                        failures.append(
                            f"Refusal answer did not contain expected keywords ({case.refusal_keywords[:3]})"
                        )
                        refusal_score = 0.5
        else:
            # Refusal was NOT expected. If the agent refused or errored unexpectedly:
            if trace.status in ("error", "refused") and not action_steps:
                failures.append("Agent refused or errored on a valid request")
                refusal_score = 0.0

        # 5. Tool Selection and Argument Matching
        tool_selection_score = 1.0
        argument_score = 1.0

        if case.expect_refusal:
            tool_selection_score = 1.0 if not action_steps else 0.0
            argument_score = 1.0
        else:
            # Match action_steps against case.expected_tools
            # Each expected tool can match up to exp.max_calls actual steps
            unmatched_steps = list(action_steps)
            matched_expected: list[tuple[ExpectedTool, ToolExecution]] = []

            for exp in case.expected_tools:
                matched_count = 0
                for step in list(unmatched_steps):
                    if exp.matches_tool_name(step.tool):
                        matched_expected.append((exp, step))
                        unmatched_steps.remove(step)
                        matched_count += 1
                        if matched_count >= exp.max_calls:
                            break
                if matched_count < exp.min_calls and exp.required:
                    failures.append(
                        f"Missing required tool call: '{exp.tool}' (called {matched_count}, expected at least {exp.min_calls})"
                    )

            # Any leftover action steps are unexpected tools
            if unmatched_steps:
                unexpected_names = [s.tool for s in unmatched_steps]
                failures.append(f"Unexpected tool calls: {unexpected_names}")

            # Compute Precision, Recall, and F1 for tool selection
            total_actual = len(action_steps)
            total_required = sum(e.min_calls for e in case.expected_tools if e.required)
            total_matched = len(matched_expected)

            prec = (total_matched / total_actual) if total_actual > 0 else (1.0 if total_required == 0 else 0.0)
            rec = min(1.0, total_matched / total_required) if total_required > 0 else 1.0

            if prec + rec > 0:
                tool_selection_score = (2 * prec * rec) / (prec + rec)
            else:
                tool_selection_score = 0.0

            # Argument validation for matched pairs
            if matched_expected:
                arg_pass_count = 0
                for exp, step in matched_expected:
                    ok_args, arg_errors = exp.validate_args(step.args)
                    if ok_args:
                        arg_pass_count += 1
                    else:
                        for err in arg_errors:
                            failures.append(f"Tool '{step.tool}': {err}")
                argument_score = arg_pass_count / len(matched_expected)
            else:
                argument_score = 0.0 if total_required > 0 else 1.0

        # 6. Composite Score
        if case.expect_refusal:
            total_score = (0.7 * refusal_score + 0.3 * tool_selection_score) * budget_score
        else:
            total_score = (0.5 * tool_selection_score + 0.5 * argument_score) * budget_score

        # 7. Final Pass status
        passed = (total_score >= self.pass_threshold) and (len(failures) == 0)

        return CaseScore(
            case_id=case.id,
            case_name=case.name,
            agent_type=case.agent_type,
            category=case.category,
            tool_selection_score=round(tool_selection_score, 3),
            argument_score=round(argument_score, 3),
            refusal_score=round(refusal_score, 3),
            budget_score=round(budget_score, 3),
            total_score=round(total_score, 3),
            passed=passed,
            failure_reasons=failures,
        )

    def score_traces(self, traces: list[ExecutionTrace]) -> ScoreReport:
        """Evaluate a batch of execution traces and produce a summary report."""
        scores = [self.score_trace(t) for t in traces]
        total = len(scores)
        passed = sum(1 for s in scores if s.passed)
        failed = total - passed
        pass_rate = (passed / total * 100.0) if total > 0 else 0.0
        mean_score = (sum(s.total_score for s in scores) / total) if total > 0 else 0.0

        return ScoreReport(
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            pass_rate=round(pass_rate, 2),
            mean_score=round(mean_score, 3),
            case_scores=scores,
        )

    def score_jsonl(self, jsonl_path: str | Path) -> ScoreReport:
        """Load and score traces from a JSONL file."""
        traces: list[ExecutionTrace] = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                d = json.loads(line)
                traces.append(ExecutionTrace.from_dict(d))
        return self.score_traces(traces)
