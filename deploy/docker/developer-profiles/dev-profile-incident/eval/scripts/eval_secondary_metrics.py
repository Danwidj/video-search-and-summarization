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

"""Secondary metrics (``secondary_metrics.py``) from saved results files. Offline: sends no request.

Usage (from ``eval/``)::

    uv run python scripts/eval_secondary_metrics.py --title "…" --out <new dir> C1=<results.json> C2=… C3=… C4=…

Only reads the results files; refuses to overwrite a report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL_DIR), str(EVAL_DIR / "scripts")]

import secondary_metrics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("configurations", nargs="+", help="NAME=<results.json>")
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = {name: Path(path) for name, _, path in (item.partition("=") for item in args.configurations)}
    targets = (args.out / "secondary-metrics.json", args.out / "secondary-metrics.md")
    if any(t.exists() for t in targets):
        print(f"REFUSED: a report exists in {args.out}", file=sys.stderr)
        return 2
    summary = {"configs": {n: secondary_metrics.secondary(json.loads(p.read_text())) for n, p in sources.items()},
               "sources": {n: {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                           for n, p in sources.items()}}
    args.out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(summary, indent=2) + "\n")
    targets[1].write_text(secondary_metrics.render(summary, args.title))
    print(targets[1].read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
