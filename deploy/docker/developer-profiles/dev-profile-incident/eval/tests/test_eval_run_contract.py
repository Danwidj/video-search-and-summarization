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

"""eval_run.run_one_video on the contract path - P1 parsed strictly, failures scored as misses."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_run  # noqa: E402
from test_contract import _valid_report  # noqa: E402


@dataclass
class _Chat:
    ok: bool
    content: str | None = None
    reasoning_content: str | None = None
    finish_reason: str | None = "stop"
    raw: dict = field(default_factory=dict)
    error: str = ""
    status_code: int | None = 200


@dataclass
class _Eval:
    fields: dict = field(default_factory=dict)
    judge_error: str = ""


class _FakeDB:
    def __init__(self):
        self.incidents = []

    def insert_incident(self, incident_id, model_run_id, *, fields):
        self.incidents.append(fields)

    def add_incident_entity(self, *a, **k):
        pass

    def add_incident_instrument(self, *a, **k):
        pass

    def add_incident_asset(self, *a, **k):
        pass


def _run(p1_result):
    db = _FakeDB()
    with (
        patch("eval_run.check_embedding_server_healthy"),
        patch("eval_run.check_judge_ok"),
        patch("eval_run.eval_gt.run_evaluation", return_value=_Eval(fields={"type": {"pass": True}})),
        patch("eval_run.score_matches_summary", return_value={"counts": {}, "matches": []}),
        patch("eval_run.analyze_video_with_p1", return_value=p1_result) as p1,
        patch("eval_run.generate_report_with_rp1", return_value=_Chat(ok=True, content="REPORT")) as rp1,
    ):
        result = eval_run.run_one_video(
            db, model="m", category="Assault", filename="A.mp4", incident_id="inc", r2_object_key="anomaly/a/A.mp4",
            video_url="https://r2.example/A.mp4?sig", gt_p1_shaped={}, model_run_id="run", split_manifest_ref="x",
        )
    return result, db, p1, rp1


def test_valid_report_is_persisted_with_derived_duration_and_rp1_runs():
    result, db, p1, rp1 = _run(_Chat(ok=True, content=json.dumps(_valid_report())))
    p1.assert_called_once_with("m", "https://r2.example/A.mp4?sig")
    assert result["p1_raw"]["contract_ok"] is True
    assert result["prediction"]["incident"]["duration"] == 8
    assert db.incidents[0]["duration"] == 8 and db.incidents[0]["type"] == "assault"
    assert rp1.call_count == 1 and result["rp1_report"]["ok"] is True
    assert result["prompt_version"] == "incident-contract-v2"
    assert "incident-contract-v2" in result["inference_config"]["response_format"]


def test_contract_violation_is_a_miss_and_rp1_is_skipped():
    bad = _valid_report()
    bad["incident"]["type"] = "fighting"
    result, db, _, rp1 = _run(_Chat(ok=True, content=json.dumps(bad)))
    assert result["p1_raw"]["contract_ok"] is False
    assert "schema violation" in result["p1_raw"]["contract_error"]
    assert result["prediction"] == eval_run.EMPTY_PREDICTION
    assert db.incidents[0]["type"] is None  # scored as an empty prediction, never repaired
    assert rp1.call_count == 0
    assert result["rp1_report"]["skipped"] is True


def test_fenced_json_is_not_extracted():
    result, _, _, _ = _run(_Chat(ok=True, content="```json\n" + json.dumps(_valid_report()) + "\n```"))
    assert result["p1_raw"]["contract_ok"] is False


def test_failed_call_is_recorded_as_contract_failure():
    result, _, _, rp1 = _run(_Chat(ok=False, error="HTTP 500", status_code=500))
    assert result["p1_raw"]["contract_ok"] is False
    assert result["p1_raw"]["contract_error"].startswith("P1 call failed")
    assert rp1.call_count == 0


def test_aggregate_counts_contract_failures_and_ignores_skipped_rp1():
    import eval_aggregate

    def video(name, ok, contract_ok, rp1_ok, skipped=False):
        return {
            "filename": name,
            "p1_raw": {"ok": ok, "contract_ok": contract_ok},
            "rp1_report": {"ok": rp1_ok, "skipped": skipped},
            "incident_field_scores": {},
            **{k: {"counts": {}, "matches": []} for k in ("entities", "instruments", "assets")},
        }

    agg = eval_aggregate.aggregate_one({"videos": [
        video("good", True, True, True),
        video("bad-contract", True, False, False, skipped=True),
        video("bad-call", False, False, False, skipped=True),
        video("bad-rp1", True, True, False),
    ]})
    assert agg["p1_failures"] == ["bad-contract", "bad-call"]
    assert agg["contract_failures"] == ["bad-contract"]
    assert agg["rp1_failures"] == ["bad-rp1"]
