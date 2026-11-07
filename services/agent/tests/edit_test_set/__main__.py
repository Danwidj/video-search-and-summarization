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

"""CLI runner for the edit and clip test set scorer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .cases import load_default_test_set
from .scorer import Scorer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline scorer for edit and clip agent test runs without hosted models."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to JSON or JSONL file with agent execution results.",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=0.99,
        help="Passing score threshold per case (default: 0.99).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of markdown summary table.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file '{input_path}' not found", file=sys.stderr)
        sys.exit(2)

    test_set = load_default_test_set()
    scorer = Scorer(test_set=test_set, pass_threshold=args.threshold)

    report = scorer.score_jsonl(input_path)

    if args.json:
        print(json.dumps(report.model_dump(), indent=2))
    else:
        print(report.summary_table())

    if report.failed_cases > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
