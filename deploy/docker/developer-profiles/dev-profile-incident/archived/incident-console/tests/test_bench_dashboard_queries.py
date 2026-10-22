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

"""``scripts/bench_dashboard_queries.py`` keeps producing the before/after numbers quoted for the Dashboard fix."""

from __future__ import annotations

import pytest

from dashboard_data import clear_evidence_cache
from scripts.bench_dashboard_queries import main


@pytest.fixture(autouse=True)
def cold_cache():
    clear_evidence_cache()
    yield
    clear_evidence_cache()


def _table(output: str) -> dict[str, list[str]]:
    rows = {}
    for line in output.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and len(cells) == 5 and cells[0] not in ("path", "---"):
            rows[cells[0]] = cells[1:]
    return rows


def test_bench_reports_108_statements_before_and_three_after_for_the_36_incident_seed(capsys):
    assert main(["--latency-ms", "0", "--repeats", "1"]) == 0
    out = capsys.readouterr().out
    assert "36 incidents" in out
    assert "a model, not Postgres" in out  # SQLite numbers are labelled as such
    rows = _table(out)
    # columns: latency, SQL statements, connection checkouts, wall-clock
    assert rows["per-incident loop (before)"][1:3] == ["108", "108"]
    assert rows["batched, cache miss (after)"][1:3] == ["3", "1"]
    assert rows["batched, cache hit (after)"][1:3] == ["0", "0"]


def test_bench_injected_latency_is_charged_per_statement_and_per_checkout(capsys):
    assert main(["--latency-ms", "5", "--checkout-round-trips", "3", "--repeats", "1"]) == 0
    rows = _table(capsys.readouterr().out)
    milliseconds = {name: float(cells[3].split()[0].replace(",", "")) for name, cells in rows.items()}
    # Sleeps never return early, so these are floors: 108 x (1 statement + 3 checkout round trips) x 5 ms
    # = 2.16 s for the loop, and (3 statements + 3 for the one checkout) x 5 ms = 30 ms for the batch.
    assert milliseconds["per-incident loop (before)"] >= 2100
    assert 29 <= milliseconds["batched, cache miss (after)"] < 1000
    assert milliseconds["batched, cache hit (after)"] < 50
