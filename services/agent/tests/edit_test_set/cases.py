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

"""Test case definitions and loader for edit and clip requests.

Covers the 20 canonical cases from scout report section 3
(10 investigator clip requests and 10 editor edit requests).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT_CASES_PATH = Path(__file__).parent / "cases.json"


class ExpectedTool(BaseModel):
    """Specification of an expected tool call and argument constraints."""

    tool: str = Field(description="Canonical tool name, e.g. 'read_report', 'look_at_clip'.")
    tool_alternatives: list[str] = Field(
        default_factory=list,
        description="Allowed naming variations/aliases, e.g. ['lab_read_report', 'incident_read_report'].",
    )
    required: bool = Field(default=True, description="Whether this tool call is strictly required.")
    min_calls: int = Field(default=1, description="Minimum number of times this tool is expected to be called.")
    max_calls: int = Field(default=1, description="Maximum number of times this tool may be called.")
    args: dict[str, Any] = Field(default_factory=dict, description="Expected exact argument values.")
    arg_tolerances: dict[str, float] = Field(
        default_factory=dict,
        description="Allowed absolute tolerances for numeric arguments, e.g. {'start_s': 0.5}.",
    )
    arg_patterns: dict[str, str] = Field(
        default_factory=dict,
        description="Regex patterns for validating string arguments, e.g. {'query': '(?i)person'}.",
    )

    def matches_tool_name(self, actual_tool: str) -> bool:
        """Check whether actual_tool matches this tool's name or any alias."""
        clean_actual = normalize_tool_name(actual_tool)
        clean_expected = normalize_tool_name(self.tool)
        if clean_actual == clean_expected:
            return True
        return any(clean_actual == normalize_tool_name(alt) for alt in self.tool_alternatives)

    def validate_args(self, actual_args: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate actual arguments against expected arguments, tolerances, and patterns."""
        errors: list[str] = []

        # 1. Exact / categorical checks
        for key, expected_val in self.args.items():
            if key not in actual_args:
                errors.append(f"Missing required argument '{key}'")
                continue
            actual_val = actual_args[key]

            # Float tolerance check if specified
            if key in self.arg_tolerances:
                tol = self.arg_tolerances[key]
                try:
                    if abs(float(actual_val) - float(expected_val)) > tol:
                        errors.append(f"Argument '{key}' expected {expected_val} +/- {tol}, got {actual_val}")
                except (ValueError, TypeError):
                    errors.append(f"Argument '{key}' expected numeric value {expected_val}, got {actual_val}")
            elif isinstance(expected_val, str) and isinstance(actual_val, str):
                if expected_val.strip().lower() != actual_val.strip().lower():
                    errors.append(f"Argument '{key}' expected '{expected_val}', got '{actual_val}'")
            elif expected_val != actual_val:
                errors.append(f"Argument '{key}' expected {expected_val!r}, got {actual_val!r}")

        # 2. Tolerances for keys without exact expected value specified in self.args
        for key, _tol in self.arg_tolerances.items():
            if key not in self.args and key in actual_args:
                # If key has no fixed baseline, ensure it is numeric
                try:
                    float(actual_args[key])
                except (ValueError, TypeError):
                    errors.append(f"Argument '{key}' must be numeric, got {actual_args[key]}")

        # 3. Pattern / regex checks
        for key, pattern in self.arg_patterns.items():
            if key not in actual_args:
                errors.append(f"Missing argument '{key}' matching pattern '{pattern}'")
                continue
            actual_val_str = str(actual_args[key])
            if not re.search(pattern, actual_val_str):
                errors.append(f"Argument '{key}' value '{actual_val_str}' failed pattern '{pattern}'")

        return len(errors) == 0, errors


class TestCase(BaseModel):
    """Specification of a single test case for an edit or clip request."""

    id: str = Field(description="Unique case identifier, e.g. 'I1', 'E3'.")
    name: str = Field(description="Short human-readable case name.")
    agent_type: Literal["investigator", "editor"] = Field(
        description="Target agent role: 'investigator' for clip QA, 'editor' for report edits."
    )
    category: str = Field(description="Specific capability or error case category.")
    request: str = Field(description="The user input request / question.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Associated context: video_id, draft, report summary, duration.",
    )
    expect_refusal: bool = Field(
        default=False,
        description="Whether the agent is expected to refuse or explain unanswerability.",
    )
    refusal_rationale: str | None = Field(
        default=None,
        description="Why refusal is expected (e.g. out of scope, unsupported modality).",
    )
    refusal_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords indicating correct refusal in answer text.",
    )
    expected_tools: list[ExpectedTool] = Field(
        default_factory=list,
        description="List of expected tool calls in this scenario.",
    )
    forbidden_tools: list[str] = Field(
        default_factory=list,
        description="Tool names that must NOT be invoked in this scenario.",
    )
    optional_tools: list[str] = Field(
        default_factory=list,
        description="Tool names allowed as intermediate steps (e.g. read_draft).",
    )
    max_steps: int = Field(
        default=5,
        description="Maximum allowed tool invocations for this request.",
    )
    description: str = Field(default="", description="Detailed explanation of the test purpose.")


class TestSet:
    """A collection of test cases with querying and filtering capabilities."""

    def __init__(self, cases: list[TestCase]) -> None:
        self.cases = cases
        self._index: dict[str, TestCase] = {c.id: c for c in cases}

    def __len__(self) -> int:
        return len(self.cases)

    def __iter__(self) -> Iterator[TestCase]:
        return iter(self.cases)

    def __getitem__(self, item: int | str) -> TestCase:
        if isinstance(item, int):
            return self.cases[item]
        if item in self._index:
            return self._index[item]
        raise KeyError(f"Case with id '{item}' not found in TestSet")

    def get(self, case_id: str, default: TestCase | None = None) -> TestCase | None:
        """Retrieve a case by ID or return default."""
        return self._index.get(case_id, default)

    def filter(
        self,
        agent_type: Literal["investigator", "editor"] | None = None,
        category: str | None = None,
        expect_refusal: bool | None = None,
    ) -> TestSet:
        """Return a new TestSet filtered by agent_type, category, or refusal expectation."""
        filtered = self.cases
        if agent_type is not None:
            filtered = [c for c in filtered if c.agent_type == agent_type]
        if category is not None:
            filtered = [c for c in filtered if c.category == category]
        if expect_refusal is not None:
            filtered = [c for c in filtered if c.expect_refusal == expect_refusal]
        return TestSet(filtered)


def normalize_tool_name(tool_name: str) -> str:
    """Normalize tool names by stripping prefixes like 'lab_' or 'incident_'."""
    name = tool_name.strip()
    for prefix in ("lab_", "incident_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    return name


def load_test_set_from_json(path: str | Path) -> TestSet:
    """Load test cases from a JSON file."""
    p = Path(path)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    cases = [TestCase.model_validate(c) for c in data]
    return TestSet(cases)


def load_default_test_set() -> TestSet:
    """Load the default canonical 20-case test set."""
    return load_test_set_from_json(DEFAULT_CASES_PATH)
