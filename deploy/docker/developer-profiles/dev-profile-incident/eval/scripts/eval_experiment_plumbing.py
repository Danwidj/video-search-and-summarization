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

"""Stage 0 step 1: an offline plumbing run of C1-C4 (plan §F.2). No network, no paid call.

Runs the four Stage 3 configurations on the **dev** half through the real runner, validator,
scorer and report, with every external dependency replaced:
- the model: a scripted P1 answer built from the ground truth (the baseline prompt is made
  to over-rate severity on every third video, so the comparisons have something to find);
- the VSS arm: the same answer wrapped in an agent ``/analyze`` 200 response, parsed by the
  real Track X handling (``vss_chat_result``), including the prompt echo;
- the judge and the embedder: deterministic token-overlap stand-ins;
- the registry: a temporary copy with one plumbing prompt standing in for the selected one.

The ground truth is the local ``ground-truth-v1.0`` **candidate**, so every result is
``reportable: false`` and the report says NOT REPORTABLE. It proves the machinery end to
end, nothing about any prompt.

Usage (from ``eval/``)::

    uv run python scripts/eval_experiment_plumbing.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contract  # noqa: E402
import embed_client  # noqa: E402
import eval_experiment  # noqa: E402
import eval_gt  # noqa: E402
import eval_gt_schema  # noqa: E402
import eval_run  # noqa: E402
import experiment_report  # noqa: E402
import experiment_runner as er  # noqa: E402
import ground_truth_freeze  # noqa: E402
import matching  # noqa: E402
import prompt_registry as pr  # noqa: E402
from eval_vlm_client import ChatResult, P1Outcome  # noqa: E402
from eval_gt import Result  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GT = EVAL_DIR / "eval_data" / "ground_truth" / ground_truth_freeze.VERSION
PLUMBING_PROMPT = "p1-v4-e00-plumbing"
MODEL = "nvidia/cosmos-3-super-reasoner"


def fake_embed(texts):
    tokenized = [re.findall(r"[a-z']+", text.lower()) for text in texts]
    vocab = sorted({word for tokens in tokenized for word in tokens})
    return embed_client.Result(ok=True, data=[[float(Counter(t).get(w, 0)) for w in vocab] for t in tokenized])


def fake_judge(expected, predicted, **_):
    a, b = set(re.findall(r"[a-z]+", (expected or "").lower())), set(re.findall(r"[a-z]+", (predicted or "").lower()))
    return Result(ok=True, data=round(len(a & b) / len(a | b), 6) if a | b else 0.0)


def scripted_answer(gt_p1: dict, *, over_rate: bool) -> str:
    """A contract-valid P1 answer carrying the ground truth's incident fields (no items)."""
    report = json.loads((contract.CONTRACTS_DIR / "fixtures" / "valid" / "minimal-report.json").read_text())
    incident = gt_p1["incident"]
    start, end = int(incident["start_timestamp"] or 0), int(incident["end_timestamp"] or 0)
    severity = int(incident["severity_level"] or 1)
    report["incident"].update({
        "type": incident["type"], "start_timestamp": start, "end_timestamp": max(start, end),
        "description": incident["description"] or "An incident.",
        "severity_level": min(5, severity + 1) if over_rate else severity,
    })
    report["timeline"] = [{"start_seconds": start, "end_seconds": max(start, end), "description": "The incident."}]
    return json.dumps(report)


def plumbing_run(out_root: Path, *, gt_dir: Path = DEFAULT_GT, split: dict | None = None,
                 now: datetime | None = None) -> dict:
    index = eval_gt_schema.load_frozen_gt_index(gt_dir, allow_candidate=True)
    sheets = ground_truth_freeze.read_frozen(gt_dir, allow_candidate=True)["sheets"]
    split = split or index["split"]
    with tempfile.TemporaryDirectory() as temp:
        registry_dir = Path(temp) / "experiments"
        shutil.copytree(pr.REGISTRY_DIR, registry_dir)
        with patch.object(pr, "REGISTRY_DIR", registry_dir), patch.object(pr, "REGISTRY_PATH",
                                                                             registry_dir / "registry.json"):
            pr.add(PLUMBING_PROMPT, parent=pr.BASE_ID, text=contract.extraction_prompt() + "\n(plumbing)\n",
                   hypothesis="Plumbing only: stands in for the selected prompt.", created="2026-10-27")
            registry = pr.load()
            decisions = Path(temp) / "decisions.md"
            decisions.write_text("# plumbing\n")
            base_pipeline = {"profile": "accuracy", "skip_rp1": True, "skip_crops": True, "agent_base_url": None}
            vss_pipeline = {**base_pipeline, "agent_base_url": "http://plumbing.invalid"}
            configs = {}
            for name, arm, prompt in (("C1", "direct-vlm", pr.BASE_ID), ("C2", "vss", pr.BASE_ID),
                                      ("C3", "vss", PLUMBING_PROMPT), ("C4", "direct-vlm", PLUMBING_PROMPT)):
                configs[name] = {
                    "experiment_id": f"plumbing-{name.lower()}", "description": "Stage 0 offline plumbing", "arm": arm,
                    "prompt_id": prompt, "model": MODEL, "split": "dev",
                    "ground_truth": {"dir": str(gt_dir), "allow_candidate": True}, "repeats": 1,
                    "budget": {"max_p1_calls": len(split["dev"])},
                    "pipeline": vss_pipeline if arm == "vss" else base_pipeline, "frozen_baseline": False,
                    "final": False, "selection_record": None, "baseline_ref": None, "videos": None}
            records = {}
            stamp = now or datetime.now(UTC)
            with patch.object(matching, "embed_texts", side_effect=fake_embed), \
                    patch.object(eval_gt, "judge_description_similarity", side_effect=fake_judge):
                for name, config in configs.items():
                    item = pr.entry(config["prompt_id"], registry)
                    dev = sorted(split["dev"])

                    def factory(incident_id, run_id, duration, _name=name, _config=config, _item=item, _dev=dev):
                        content = scripted_answer(index["by_incident_id"][incident_id]["p1_shaped"],
                                                  over_rate=_name in ("C1", "C2") and _dev.index(incident_id) % 3 == 0)
                        if _config["arm"] == "direct-vlm":
                            return lambda *_: P1Outcome(ChatResult(ok=True, content=content, finish_reason="stop",
                                                                   elapsed_s=10.0), [])
                        echo = {"prompt_id": _item["id"], "prompt_sha256": _item["sha256"]}
                        body = {"raw_output": content, "contract_version": contract.contract_version(),
                                "finish_reason": "stop", "model": MODEL, "experiment": echo, "p1_elapsed_ms": 10000.0,
                                "usage": {}}
                        result = er.vss_chat_result(er.VSSResponse(200, body, 12.5), prompt_id=_item["id"],
                                                    prompt_sha256=_item["sha256"], started_at="s", finished_at="f")
                        return lambda *_: P1Outcome(result, [])

                    def run_one(*args, **kwargs):
                        kwargs["incident_only"] = True
                        return eval_run.run_one_video(*args, **kwargs)

                    out = er.run_experiment(
                        config, split=split, gt_index=index, store=eval_experiment.frozen_store(sheets),
                        video_source=lambda i: ("plumbing://no-video", {"r2_object_key": i, "duration_seconds": None}),
                        call_factory=factory, run_one=run_one, confirm_paid=True, results_root=out_root,
                        registry=registry, decisions_path=decisions, now=stamp, log=lambda *_: None)
                    records[name] = json.loads(Path(out["results"]).read_text())
            checks = {name: experiment_report.verify(Path(out_root / configs[name]["experiment_id"] /
                                                          stamp.strftime("%Y%m%dT%H%M%SZ")), registry=registry,
                                                     split=split) for name in configs}
    report = experiment_report.render(records, title="Stage 0 offline plumbing run (C1–C4, dev, scripted model)")
    report_path = out_root / f"plumbing-report-{stamp.strftime('%Y%m%dT%H%M%SZ')}.md"
    report_path.write_text(report)
    return {"records": records, "verify": checks, "report": report_path,
            "comparisons": er.four_way(records)}


def main() -> int:
    result = plumbing_run(er.RESULTS_ROOT)
    summary = {name: {"videos": len(r["videos"]), "reportable": r["reportable"],
                      "outcomes": r["reliability"]["outcomes"]} for name, r in result["records"].items()}
    severity = {name: block["fields"]["severity_level"]["mean_difference"]
                for name, block in result["comparisons"]["comparisons"].items()}
    print(json.dumps({"configurations": summary, "verify_problems": result["verify"],
                      "severity_mean_difference": severity, "comparison_problems": result["comparisons"]["problems"],
                      "report": str(result["report"])}, indent=2))
    return 0 if not any(result["verify"].values()) and not result["comparisons"]["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
