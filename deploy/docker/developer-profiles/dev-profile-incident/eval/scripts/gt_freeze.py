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

"""Prepare the ground-truth-v1.0 candidate, and freeze it only with an explicit approval record (PR 5).

The corrected records are rebuilt from the unchanged source workbook plus the review decisions
in the latest reviewed candidate workbook (``Ground Truth Candidate <v>.xlsx``), exactly as
``gt_candidate_build.py`` applies them. Then:

- schema validation (``ground_truth_freeze.schema_problems``) against the guidelines and the
  dataset manifest;
- ``split-v2`` from the seeded split manifests (25 dev / 55 test, membership unchanged) and its
  consistency checks;
- the blocking issues: any entry still ``Pending`` blocks, it is never treated as Approved;
- ``MANIFEST.json`` with the SHA-256 of every output and input, the generator's git SHA, the
  guideline, methodology and correction-prompt versions, and the status.

Status is ``frozen`` only when nothing blocks and ``--approval`` names exactly this candidate
(its workbook SHA-256, its records digest and its exclusions) with who approved it and when.
Otherwise the directory is written as a ``candidate``, which ``read_frozen`` refuses unless asked.
A directory already ``frozen`` is never overwritten: a correction is a new version (v1.1).

Outputs go to ``eval_data/ground_truth/<version>/`` (gitignored: where frozen ground truth is
stored, decision D7, is not settled). The readiness report beside the review files is ids and
counts only.

Usage (from ``eval/``)::

    uv run python scripts/gt_freeze.py --candidate "ground_truth/review/Ground Truth Candidate v0.2.xlsx"
    uv run python scripts/gt_freeze.py --candidate … --approval ground_truth/freeze/ground-truth-v1.0-approval.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ground_truth_correction as gtc  # noqa: E402
import ground_truth_freeze as gtf  # noqa: E402
import ground_truth_review as gtr  # noqa: E402
import methodology  # noqa: E402
import openpyxl  # noqa: E402
import review_backup  # noqa: E402
from gt_candidate_build import FRAMES_DIR, PROMPT_PATH  # noqa: E402
from gt_review_build import DEFAULT_MANIFEST, DEFAULT_OUT_DIR, DEFAULT_SOURCE, EVAL_DIR, sha256_file  # noqa: E402

GENERATOR = "gt_freeze.py v1"
DEFAULT_SPLITS = sorted((EVAL_DIR / "eval_reproducibility").glob("split_*.json"))
DEFAULT_OUT = EVAL_DIR / "eval_data" / "ground_truth"
REPORT_DIR = EVAL_DIR / "ground_truth" / "freeze"


def corrected(source: Path, manifest: dict, candidate: Path, proposals_path: Path, frames_dir: Path):
    values = openpyxl.load_workbook(source, data_only=True)
    changes, _ = gtr.audit(values, manifest)
    log = gtc.read_change_log(openpyxl.load_workbook(candidate, data_only=True))
    problems = gtc.check_carry_forward(changes, log)
    if problems:
        raise ValueError(f"{candidate.name} does not match the audit: {problems[:3]}")
    verification = {c.change_id: gtc.verify_mechanical(c, values, manifest) for c in changes
                    if c.change_type == "verified_correction"}
    proposals = gtc.load_proposals(proposals_path)
    by_id = {c.change_id: c for c in changes}
    proposal_problems = {}
    for change_id, proposal in proposals.items():
        frames_file = frames_dir / by_id[change_id].incident_id / "frames.json" if change_id in by_id else None
        frames = json.loads(frames_file.read_text()) if frames_file and frames_file.exists() else None
        proposal_problems[change_id] = (gtc.validate_proposal(proposal, by_id[change_id], frames)
                                        if change_id in by_id else ["no such change"])
    # Only a person's Approved/Rejected is read from the workbook; Auto-verified is re-derived, never trusted.
    prior = {str(row["Change ID"]): row for row in log}
    entries = gtc.resolve(changes, prior=prior, prior_name=candidate.name, verification=verification,
                          proposals=proposals, proposal_problems=proposal_problems)
    return entries, gtc.apply_to_records(gtr.read_data_rows(values), entries)


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=EVAL_DIR,
                              check=False).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def report(result: dict) -> str:
    lines = [
        f"# {gtf.VERSION} readiness",
        "",
        f"> Generated by `eval/scripts/gt_freeze.py`. Status: **{result['status']}**. A candidate is not ground truth: "
        "it is frozen only with no blocking issue and an approval record for exactly this candidate. Ids and counts "
        "only.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Candidate workbook | `{result['inputs']['candidate_workbook']['name']}` "
        f"`{result['inputs']['candidate_workbook']['sha256']}` |",
        f"| Review state | {result['inputs']['candidate_workbook']['review_state']['statuses']} |",
        f"| Records digest | `{result['records_sha256']}` |",
        f"| Records | {result['records']} |",
        f"| Split | {gtf.SPLIT_VERSION}: {result['split']['dev']} dev / {result['split']['test']} test "
        f"(excluded: {result['split']['excluded'] or 'none'}) |",
        f"| Entries | {result['entries']} |",
        "",
        "## Blocking",
        "",
    ]
    lines += [f"- {reason}" for reason in result["blocking"]] or ["- Nothing blocks."]
    lines += ["", "## Validation", "",
              f"- Schema problems: {len(result['schema_problems'])}" + "".join(f"\n  - {p}" for p in result["schema_problems"]),
              f"- Split problems: {len(result['split_problems'])}" + "".join(f"\n  - {p}" for p in result["split_problems"]),
              ""]
    return "\n".join(lines)


def freeze(source: Path, manifest_path: Path, candidate: Path, proposals: Path, split_paths: list[Path],
           out_root: Path, *, approval_path: Path | None = None, frames_dir: Path = FRAMES_DIR,
           report_dir: Path | None = REPORT_DIR) -> dict:
    gtc.guard_inputs([source, manifest_path, candidate, proposals, *split_paths])
    out = out_root / gtf.VERSION
    if (out / "MANIFEST.json").exists() and json.loads((out / "MANIFEST.json").read_text()).get("status") == "frozen":
        raise review_backup.OverwriteRefusedError(f"{out} is frozen; a correction is a new version, never an overwrite")
    hashes = {p: sha256_file(p) for p in (source, candidate)}
    manifest = json.loads(manifest_path.read_text())
    entries, records = corrected(source, manifest, candidate, proposals, frames_dir)
    split = gtf.split_v2([json.loads(p.read_text()) for p in split_paths])
    approval = json.loads(approval_path.read_text()) if approval_path else None
    exclusions = sorted((approval or {}).get("exclusions") or [])
    records, split = gtf.apply_exclusions(records, split, exclusions)
    gtf.mark_uncertain(records, entries)
    records_sha = gtc.records_digest(records)
    schema = gtf.schema_problems(records, manifest) if not exclusions else [
        p for p in gtf.schema_problems(records, manifest) if not p.startswith("clips without")]
    split_issues = gtf.split_problems(split, records, expected=(len(split["dev"]), len(split["test"])) if exclusions
                                      else (25, 55))
    issues = gtf.blocking_issues(entries, schema, split_issues)
    status, reasons = gtf.freeze_status(issues, approval, workbook_sha256=hashes[candidate], records_sha256=records_sha,
                                        exclusions=exclusions)
    data = {"version": gtf.VERSION, "status": status, "guidelines": gtr.GUIDELINE_VERSION,
            "methodology": methodology.METHODOLOGY_VERSION, "sheets": records}
    files = {"ground_truth.json": gtf.canonical_json(data), "split-v2.json": gtf.canonical_json(split)}
    result = {
        "version": gtf.VERSION,
        "status": status,
        "blocking": reasons,
        "generator": GENERATOR,
        "git_sha": _git_sha(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": {name: gtf.sha256_bytes(content) for name, content in files.items()},
        "records_sha256": records_sha,
        "records": {sheet: len(rows) for sheet, rows in records.items()},
        "split": {"dev": len(split["dev"]), "test": len(split["test"]), "excluded": split.get("excluded", [])},
        "entries": dict(sorted(Counter(e.status for e in entries).items())),
        "applied": sum(e.applied for e in entries),
        "schema_problems": schema,
        "split_problems": split_issues,
        "inputs": {
            "source_workbook": {"name": source.name, "sha256": hashes[source]},
            "candidate_workbook": {"name": candidate.name, "sha256": hashes[candidate],
                                   "review_state": review_backup.review_state(candidate)},
            "ai_proposals": {"name": proposals.name, "sha256": sha256_file(proposals) if proposals.exists() else None},
            "dataset_manifest": {"clips_sha256": manifest["clips_sha256"]},
            "split_manifests": {p.name: sha256_file(p) for p in split_paths},
            "correction_prompt": {"version": gtc.CORRECTION_PROMPT_VERSION, "sha256": sha256_file(PROMPT_PATH)},
            "guidelines": gtr.GUIDELINE_VERSION,
            "methodology": methodology.METHODOLOGY_VERSION,
            "approval": {"name": approval_path.name, "sha256": sha256_file(approval_path)} if approval_path else None,
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_bytes(content)
    (out / "MANIFEST.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    for path, digest in hashes.items():
        if sha256_file(path) != digest:
            raise RuntimeError(f"{path.name} changed while freezing")
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / f"{gtf.VERSION}-readiness.md").write_text(report(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare (and, with approval, freeze) ground-truth-v1.0.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_OUT_DIR / "Ground Truth Candidate v0.2.xlsx",
                        help="The latest reviewed candidate workbook (its statuses are the decisions)")
    parser.add_argument("--proposals", type=Path, help="AI proposals JSONL (default: ai-proposals-<candidate version>)")
    parser.add_argument("--approval", type=Path, help="Approval record; without it the output is a candidate")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    version = args.candidate.stem.rsplit(" ", 1)[-1]
    proposals = args.proposals or args.candidate.parent / f"ai-proposals-{version}.jsonl"
    try:
        result = freeze(args.source, args.manifest, args.candidate, proposals, DEFAULT_SPLITS, args.out_root,
                        approval_path=args.approval)
    except review_backup.OverwriteRefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: result[k] for k in ("status", "records", "split", "entries", "applied", "records_sha256")},
                     indent=2))
    for reason in result["blocking"][:8]:
        print(f"  blocking: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
