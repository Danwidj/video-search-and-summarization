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

"""Controlled recovery of infrastructure-failed video-runs (protocol ``recovery-v1``).

- **Only infrastructure failures are recovered:** a video-run whose request never produced a
  model output (rate limit, timeout, host suspended, transport error, or an agent 500 wrapping an
  upstream 429 or gateway timeout). A model output, valid or not, is never re-run.
- **The original result is never changed.** A recovery is a separate, immutable result
  (``<experiment>-recovery``), run under retry-v2 and interleaved across arms by the D10 order.
  Every recovered video-run carries ``recovers``, which links it to the original attempt.
- **Merging** writes a third record, ``protocol: original+recovery-v1``. Its ``reliability_original``
  is the original run's reliability, and ``reliability`` is that of the merged view. Records of
  different protocols never meet in one comparison (D9 G3).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import experiment_runner as er
import extraction_stats

PROTOCOL = "recovery-v1"
MERGED_PROTOCOL = "original+recovery-v1"
RECOVERY_RETRY_POLICY = "retry-v2"
RECOVERABLE = ("rate_limited", "timeout", "host_suspended", "transport_error")
GATEWAY_TIMEOUTS = (504, 522, 524)
# The most video-runs one recovery re-attempts per configuration (approved hard budget, 2026-10-28). More than this
# after retry-v2 means a persistent outage: the recovery is refused and the stage is reported instead.
MAX_RECOVERED_RUNS = 15


def failure_class(video: dict) -> str | None:
    """The infrastructure failure of a video-run with no model output, else ``None``.

    Records written before the runner recognised a wrapped upstream status (Stage 1) are classified
    here from the stored error text, so an agent 500 wrapping a 429 or a 524 is recoverable.
    """
    if extraction_stats.has_model_output(video):
        return None
    raw = video.get("p1_raw") or {}
    if video.get("outcome") in RECOVERABLE:
        return video["outcome"]
    if raw.get("failure_kind") in RECOVERABLE:
        return raw["failure_kind"]
    status = er._upstream_status({"detail": raw.get("error") or ""})
    if status is None and isinstance(raw.get("error"), str):
        try:
            status = er._upstream_status(json.loads(raw["error"]))
        except ValueError:
            status = None
    if status == 429:
        return "rate_limited"
    if status in GATEWAY_TIMEOUTS:
        return "timeout"
    return None


def plan(record: dict, *, results_path: str, results_sha256: str) -> dict:
    """The video-runs one recovery would re-attempt, and the failures it deliberately leaves alone."""
    runs, left = [], []
    for video in record["videos"]:
        if extraction_stats.has_model_output(video):
            continue
        cls = failure_class(video)
        entry = {"repeat": video["repeat"], "incident_id": video["incident_id"], "position": video.get("position"),
                 "run_id": video.get("run_id"), "outcome": video["outcome"], "class": cls}
        (runs if cls else left).append(entry)
    return {"experiment_id": record["experiment_id"], "protocol": PROTOCOL,
            "of": {"results": results_path, "results_sha256": results_sha256,
                   "experiment_id": record["experiment_id"], "protocol": record.get("protocol", "original")},
            "runs": runs, "not_recoverable": left}


class RecoveryRefused(RuntimeError):
    pass


def recovery_config(original: dict, recovery_plan: dict, gt_index: dict, *, max_runs: int = MAX_RECOVERED_RUNS) -> dict:
    """The recovery's own configuration: the original's, under retry-v2, capped for the listed runs only."""
    config = copy.deepcopy(original)
    runs = recovery_plan["runs"]
    if len(runs) > max_runs:
        raise RecoveryRefused(f"{original['experiment_id']}: {len(runs)} infrastructure-failed video-runs exceed the "
                              f"recovery limit of {max_runs}; report the outage instead of recovering")
    attempts = len(runs) * (1 + er.P1_RATE_LIMIT_RETRIES)
    judge = er.subset_judge_cap(original, {(r["repeat"], r["incident_id"]) for r in runs}, gt_index)["required"]
    config.update(
        experiment_id=f"{original['experiment_id']}-recovery",
        description=f"recovery-v1 of {original['experiment_id']}: only its infrastructure-failed video-runs",
        videos=sorted({r["incident_id"] for r in runs}), frozen_baseline=False,
        budget={"max_p1_calls": attempts, "max_p1_tokens": attempts * er.P1_TOKENS_CEILING,
                "max_judge_calls": max(1, judge)})
    config["pipeline"] = {**config["pipeline"], "retry_policy": RECOVERY_RETRY_POLICY}
    return config


def links(recovery_plan: dict) -> dict:
    return {"of": recovery_plan["of"],
            "links": {(r["repeat"], r["incident_id"]): {k: r[k] for k in ("position", "run_id", "outcome", "class")}
                      for r in recovery_plan["runs"]}}


def merge(original: dict, recovery: dict, *, recovery_path: str, recovery_sha256: str) -> dict:
    """The merged view: each recovered video-run replaces its original; everything is labelled."""
    if recovery.get("protocol") != PROTOCOL or recovery["recovers"]["experiment_id"] != original["experiment_id"]:
        raise ValueError("not a recovery of this result")
    replaced = {(v["repeat"], v["incident_id"]): v for v in recovery["videos"]}
    videos = []
    for video in original["videos"]:
        key = (video["repeat"], video["incident_id"])
        if key in replaced:
            videos.append({**replaced[key], "recovered_from": {"position": video.get("position"),
                                                               "run_id": video.get("run_id"),
                                                               "outcome": video["outcome"]}})
        else:
            videos.append(video)
    merged = copy.deepcopy(original)
    merged.update(
        protocol=MERGED_PROTOCOL, videos=videos, complete=bool(original.get("complete") and recovery.get("complete")),
        reliability_original=original.get("reliability") or extraction_stats.reliability(original["videos"]),
        reliability=extraction_stats.reliability(videos),
        recovery={"results": recovery_path, "results_sha256": recovery_sha256, "recovered": len(replaced),
                  "recovered_with_output": sum(1 for v in replaced.values() if extraction_stats.has_model_output(v)),
                  "retry_policy": RECOVERY_RETRY_POLICY, "usage": recovery.get("usage")})
    return merged


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
