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

"""VLM benchmark tables from one ``eval_run.py`` run. Read-only: never re-scores.

Input is one immutable run directory (``eval_data/results/runs/<run start>/``,
default the newest), so every row comes from the same run. Output goes to
``eval_data/results/benchmark/<run start>/``:

- ``benchmark_per_video.csv``: one row per (video, model). Every attempted pair is
  a row (``outcome``, ``eval_run_lib.classify_outcome``); a video never sent to a
  model is a ``not_attempted`` row. Rate-limit retries and waits are recorded per row.
- ``benchmark_by_model.{json,csv,md}`` and ``benchmark_by_category_and_model.csv``:
  each incident field under its existing metric (``eval_gt.compare_incident_fields``),
  processing time, call outcomes and the video set's size and length.

Incident fields only. The primary fields are type, severity_level,
start_timestamp, end_timestamp and description; ``duration`` is end - start, so it
is reported as a derived diagnostic, not a headline metric. There is deliberately
no overall or blended score: each field stays separate (as in ``eval_aggregate``).

Field metrics cover **model outputs only** (``model_quality_row``): ``scored``
(core fields valid; the field scores say how accurate), ``contract_invalid`` and
``parse_failure``, the last two counting as a miss on every field. Requests that
produced no model output (``rate_limited``, ``timeout``, ``http_error``) are
reported separately and never counted as a wrong prediction. (``eval_aggregate``
still counts every failure as a miss.) Mean absolute error is over rows where both
sides have a value. Model-level figures are computed from the per-video rows, so
every video weighs the same.

Processing time is ``timing.p1_elapsed_s``: the successful P1 HTTP round trip
(``eval_vlm_client.chat_completion``), never pacing or rate-limit waits. A failed
final attempt keeps its time separately (``final_attempt_time_s``).

Usage::

    uv run python scripts/eval_benchmark_export.py                 # newest run
    uv run python scripts/eval_benchmark_export.py --run-dir eval_data/results/runs/<run start>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contract  # noqa: E402
from eval_dataset_stats import BYTES_PER_MB, summary_stats  # noqa: E402
from eval_run_lib import ALL_OUTCOMES, MODEL_OUTPUT_OUTCOMES, classify_outcome  # noqa: E402
from eval_ingest_gt import EVAL_DATA_DIR  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"
PRIMARY_EXACT_FIELDS = ("type", "severity_level")
PRIMARY_TOLERANCE_FIELDS = ("start_timestamp", "end_timestamp")
DERIVED_TOLERANCE_FIELDS = ("duration",)

PER_VIDEO_COLUMNS = [
    "category", "filename", "incident_id", "r2_object_key", "video_duration_s", "video_size_bytes", "video_size_mb",
    "model_id", "outcome", "model_quality_row", "p1_ok", "contract_ok", "core_ok", "finish_reason", "error",
    "processing_time_s", "final_attempt_time_s", "p1_started_at", "prompt_tokens", "completion_tokens",
    "attempt_count", "rate_limit_retries", "rate_limit_wait_s", "judge_calls",
    "type_expected", "type_predicted", "type_pass",
    "severity_level_expected", "severity_level_predicted", "severity_level_pass",
    "start_timestamp_expected", "start_timestamp_predicted", "start_timestamp_abs_err_s", "start_timestamp_pass",
    "end_timestamp_expected", "end_timestamp_predicted", "end_timestamp_abs_err_s", "end_timestamp_pass",
    "description_score", "description_pass",
    "derived_duration_expected", "derived_duration_predicted", "derived_duration_abs_err_s", "derived_duration_pass",
]


def newest_run_dir(results_dir: Path = RESULTS_DIR) -> Path:
    runs = sorted(p for p in (results_dir / "runs").glob("*") if p.is_dir())
    if not runs:
        raise FileNotFoundError(f"no runs under {results_dir / 'runs'} - run eval_run.py first")
    return runs[-1]


def load_run(run_dir: Path) -> list[dict]:
    files = sorted(run_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no result files in {run_dir}")
    return [json.loads(f.read_text()) for f in files]


def load_dataset_videos(results_dir: Path = RESULTS_DIR) -> dict[str, dict]:
    """``{filename: row}`` from ``dataset_stats.json`` - only a fallback for runs written before ``video`` existed."""
    path = results_dir / "dataset_stats.json"
    if not path.exists():
        return {}
    return {row["filename"]: row for row in json.loads(path.read_text())["videos"]}


def _abs_err(entry: dict) -> float | None:
    expected, predicted = entry.get("expected"), entry.get("predicted")
    if expected is None or predicted is None:
        return None
    try:
        return abs(float(expected) - float(predicted))
    except (TypeError, ValueError):
        return None


def _first_known(*values):
    return next((v for v in values if v is not None), None)


def per_video_row(video: dict, *, model_id: str, dataset_videos: dict[str, dict]) -> dict:
    p1_raw = video.get("p1_raw", {})
    fields = video.get("incident_field_scores", {})
    usage = p1_raw.get("usage") or {}
    timing = video.get("timing") or {}
    rate_limit = p1_raw.get("rate_limit") or {}
    outcome = classify_outcome(p1_raw, video.get("validation"))
    meta = video.get("video") or {}
    fallback = dataset_videos.get(video["filename"], {})
    size = _first_known(meta.get("size_bytes"), fallback.get("size_bytes"))
    duration = _first_known(meta.get("duration_seconds"), (video.get("validation") or {}).get("video_duration_seconds"),
                            fallback.get("duration_seconds"))

    row = {
        "category": video.get("category"), "filename": video["filename"], "incident_id": video.get("incident_id"),
        "r2_object_key": video.get("r2_object_key"), "video_duration_s": duration, "video_size_bytes": size,
        "video_size_mb": size / BYTES_PER_MB if size is not None else None,
        "model_id": model_id, "outcome": outcome, "model_quality_row": outcome in MODEL_OUTPUT_OUTCOMES,
        "p1_ok": bool(p1_raw.get("ok")),
        "contract_ok": bool(p1_raw.get("contract_ok")), "core_ok": bool(p1_raw.get("core_ok", p1_raw.get("contract_ok"))),
        "finish_reason": p1_raw.get("finish_reason"), "error": p1_raw.get("error") or "",
        # Only a successful round trip is processing time (older records timed failures too).
        "processing_time_s": timing.get("p1_elapsed_s") if p1_raw.get("ok") else None,
        "final_attempt_time_s": _first_known(timing.get("final_attempt_elapsed_s"), timing.get("p1_elapsed_s")),
        "p1_started_at": timing.get("started_at"),
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        "attempt_count": rate_limit.get("attempt_count", 1),
        "rate_limit_retries": rate_limit.get("rate_limit_retries", 0),
        "rate_limit_wait_s": sum(a.get("wait_before_s", 0.0) for a in rate_limit.get("attempts", [])
                                 if a.get("wait_reason") == "rate_limit_cooldown"),
        "judge_calls": video.get("judge_calls"),
    }
    for name in PRIMARY_EXACT_FIELDS:
        entry = fields.get(name, {})
        row.update({f"{name}_expected": entry.get("expected"), f"{name}_predicted": entry.get("predicted"),
                    f"{name}_pass": entry.get("pass")})
    for name in PRIMARY_TOLERANCE_FIELDS:
        entry = fields.get(name, {})
        row.update({f"{name}_expected": entry.get("expected"), f"{name}_predicted": entry.get("predicted"),
                    f"{name}_abs_err_s": _abs_err(entry), f"{name}_pass": entry.get("pass")})
    description = fields.get("description", {})
    row.update(description_score=description.get("score"), description_pass=description.get("pass"))
    duration_entry = fields.get("duration", {})
    row.update(derived_duration_expected=duration_entry.get("expected"),
               derived_duration_predicted=duration_entry.get("predicted"),
               derived_duration_abs_err_s=_abs_err(duration_entry), derived_duration_pass=duration_entry.get("pass"))
    return row


def not_attempted_row(skipped: dict, *, category: str, model_id: str, dataset_videos: dict[str, dict]) -> dict:
    fallback = dataset_videos.get(skipped["filename"], {})
    size = fallback.get("size_bytes")
    row = dict.fromkeys(PER_VIDEO_COLUMNS)
    row.update(category=category, filename=skipped["filename"], r2_object_key=fallback.get("r2_object_key"),
               video_duration_s=fallback.get("duration_seconds"), video_size_bytes=size,
               video_size_mb=size / BYTES_PER_MB if size is not None else None,
               model_id=model_id, outcome="not_attempted", model_quality_row=False,
               p1_ok=False, contract_ok=False, core_ok=False,
               error=skipped.get("reason", ""))
    return row


def build_rows(payloads: list[dict], dataset_videos: dict[str, dict]) -> list[dict]:
    rows = []
    for payload in payloads:
        model_id, category = payload["model_id"], payload["category"]
        for video in payload["videos"]:
            rows.append(per_video_row({"category": category, **video}, model_id=model_id, dataset_videos=dataset_videos))
        for skipped in payload.get("skipped_videos", []):
            rows.append(not_attempted_row(skipped, category=category, model_id=model_id, dataset_videos=dataset_videos))
    return sorted(rows, key=lambda r: (r["category"] or "", r["filename"], r["model_id"]))


def _pct(flags: list) -> float | None:
    return round(100.0 * sum(1 for f in flags if f) / len(flags), 1) if flags else None


def _tolerance_block(rows: list[dict], prefix: str) -> dict:
    errors = [r[f"{prefix}_abs_err_s"] for r in rows]
    return {"tolerance_accuracy_pct": _pct([r[f"{prefix}_pass"] for r in rows]),
            "mean_abs_error_s": summary_stats(errors)["mean"], "mae_n": summary_stats(errors)["n"]}


def summarize_rows(rows: list[dict]) -> dict:
    """One block of metrics over a set of (video, model) rows - each field separate, no blended score.

    Field metrics use model outputs only (``model_quality_row``); rows without a
    model output (rate limit, timeout, HTTP failure, not attempted) are only counted.
    """
    attempted = [r for r in rows if r["outcome"] != "not_attempted"]
    quality = [r for r in attempted if r["model_quality_row"]]
    completed = [r for r in attempted if r["p1_ok"]]
    failed_calls = [r for r in attempted if not r["p1_ok"]]
    descriptions = [r["description_score"] for r in quality]
    outcomes = {name: sum(1 for r in rows if r["outcome"] == name) for name in (*ALL_OUTCOMES, "not_attempted")}
    return {
        "num_attempted": len(attempted),
        "num_model_outputs": len(quality),
        "outcomes": outcomes,
        "num_contract_valid": sum(1 for r in attempted if r["contract_ok"]),
        "rate_limit": {
            "retries": sum(r["rate_limit_retries"] or 0 for r in attempted),
            "rows_with_429": sum(1 for r in attempted if (r["rate_limit_retries"] or 0) > 0
                                 or r["outcome"] == "rate_limited"),
            "wait_s": sum(r["rate_limit_wait_s"] or 0.0 for r in attempted),
        },
        "primary_fields": {
            "type": {"accuracy_pct": _pct([r["type_pass"] for r in quality])},
            "severity_level": {"accuracy_pct": _pct([r["severity_level_pass"] for r in quality])},
            "start_timestamp": _tolerance_block(quality, "start_timestamp"),
            "end_timestamp": _tolerance_block(quality, "end_timestamp"),
            "description": {"mean_judge_score": summary_stats(descriptions)["mean"],
                            "n_scored": summary_stats(descriptions)["n"],
                            "pass_pct": _pct([r["description_pass"] for r in quality])},
        },
        "derived_diagnostics": {"duration": _tolerance_block(quality, "derived_duration")},
        "processing_time_s": summary_stats([r["processing_time_s"] for r in completed]),
        "failed_call_time_s": summary_stats([r["final_attempt_time_s"] for r in failed_calls]),
        "completion_tokens": summary_stats([r["completion_tokens"] for r in completed]),
        "videos": {
            "duration_s": summary_stats([r["video_duration_s"] for r in quality]),
            "size_mb": summary_stats([r["video_size_mb"] for r in quality]),
        },
        "failures": [{"category": r["category"], "filename": r["filename"], "outcome": r["outcome"], "error": r["error"]}
                     for r in rows if r["outcome"] != "scored"],
    }


def dataset_summary(rows: list[dict]) -> dict:
    """The video set itself, one entry per video (not per model)."""
    videos = {}
    for r in rows:
        videos.setdefault(r["filename"], r)
    return {
        "num_videos": len(videos),
        "duration_s": summary_stats([r["video_duration_s"] for r in videos.values()]),
        "size_mb": summary_stats([r["video_size_mb"] for r in videos.values()]),
    }


def model_notes() -> dict[str, str]:
    """Per-model caveats recorded in contracts/inference.json (e.g. Cosmos-3-Super's frame sampling)."""
    inference = json.loads((contract.CONTRACTS_DIR / "inference.json").read_text())
    return {m["id"]: m["notes"] for m in inference["models"] if m.get("notes")}


def build_summary(rows: list[dict], payloads: list[dict], run_dir: Path) -> dict:
    models = sorted({r["model_id"] for r in rows})
    categories = sorted({r["category"] for r in rows})
    video_sets = {m: {r["filename"] for r in rows if r["model_id"] == m} for m in models}
    all_videos = set().union(*video_sets.values()) if video_sets else set()
    first = payloads[0] if payloads else {}
    return {
        "run_dir": str(run_dir),
        "prompt_version": first.get("prompt_version"),
        "validation_policy": first.get("validation_policy"),
        "inference_config": first.get("inference_config"),
        "benchmark": first.get("benchmark"),
        "model_notes": model_notes(),
        "metric_definitions": {
            "denominator": "model outputs only (scored, contract_invalid, parse_failure); rate limits, timeouts "
                           "and HTTP failures are reported separately, never as a wrong prediction",
            "type": "exact match after lowercase/strip; % of model outputs",
            "severity_level": "exact integer match; % of model outputs",
            "start_timestamp": "within +/-5 s of ground truth (% of model outputs); MAE over rows with both values",
            "end_timestamp": "within +/-5 s of ground truth (% of model outputs); MAE over rows with both values",
            "description": "LLM-judge semantic score 0-1 (mean over model outputs); pass if >= 0.5; an empty "
                           "predicted description scores 0.0 without a judge call",
            "timeouts": "no model output: counted under outcomes, never in prediction metrics",
            "derived_duration": "end - start; diagnostic only, not an independent field",
            "processing_time_s": "the successful P1 HTTP round trip, request sent -> full response received; "
                                 "excludes pacing and rate-limit waits",
        },
        "dataset": dataset_summary(rows),
        "missing_videos_by_model": {m: sorted(all_videos - s) for m, s in video_sets.items() if all_videos - s},
        "by_model": {m: summarize_rows([r for r in rows if r["model_id"] == m]) for m in models},
        "by_category_and_model": {
            c: {m: summarize_rows([r for r in rows if r["category"] == c and r["model_id"] == m]) for m in models}
            for c in categories
        },
    }


def flat_summary_row(block: dict, **keys) -> dict:
    fields, time = block["primary_fields"], block["processing_time_s"]
    return {
        **keys,
        "num_attempted": block["num_attempted"], "num_model_outputs": block["num_model_outputs"],
        **{f"n_{k}": v for k, v in block["outcomes"].items()},
        "rate_limit_retries": block["rate_limit"]["retries"], "rows_with_429": block["rate_limit"]["rows_with_429"],
        "n_contract_valid": block["num_contract_valid"],
        "type_accuracy_pct": fields["type"]["accuracy_pct"],
        "severity_level_accuracy_pct": fields["severity_level"]["accuracy_pct"],
        "start_timestamp_within_5s_pct": fields["start_timestamp"]["tolerance_accuracy_pct"],
        "start_timestamp_mae_s": fields["start_timestamp"]["mean_abs_error_s"],
        "end_timestamp_within_5s_pct": fields["end_timestamp"]["tolerance_accuracy_pct"],
        "end_timestamp_mae_s": fields["end_timestamp"]["mean_abs_error_s"],
        "description_mean_judge_score": fields["description"]["mean_judge_score"],
        "description_pass_pct": fields["description"]["pass_pct"],
        "derived_duration_within_5s_pct": block["derived_diagnostics"]["duration"]["tolerance_accuracy_pct"],
        "derived_duration_mae_s": block["derived_diagnostics"]["duration"]["mean_abs_error_s"],
        "processing_time_n": time["n"], "processing_time_mean_s": time["mean"],
        "processing_time_median_s": time["median"], "processing_time_p90_s": time["p90"],
        "processing_time_min_s": time["min"], "processing_time_max_s": time["max"],
        "completion_tokens_mean": block["completion_tokens"]["mean"],
        "video_duration_mean_s": block["videos"]["duration_s"]["mean"],
        "video_size_mean_mb": block["videos"]["size_mb"]["mean"],
    }


def _fmt(value, digits: int = 1, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.{digits}f}{suffix}"


def markdown(summary: dict) -> str:
    ds = summary["dataset"]
    lines = [
        "# VLM benchmark - incident fields",
        "",
        f"Run: `{summary['run_dir']}` - {summary['prompt_version']}, policy {summary['validation_policy']}.",
        "",
        "## Video set",
        "",
        "| Videos | Mean length | Median length | Mean size | Median size |",
        "|---|---|---|---|---|",
        (f"| {ds['num_videos']} | {_fmt(ds['duration_s']['mean'], 1, ' s')} | {_fmt(ds['duration_s']['median'], 1, ' s')} "
         f"| {_fmt(ds['size_mb']['mean'], 2, ' MB')} | {_fmt(ds['size_mb']['median'], 2, ' MB')} |"),
        "",
        "## Incident fields by model (each field separate; no blended score)",
        "",
        "| Model | Model outputs | Type acc. | Severity acc. | Start ±5 s (MAE) | End ±5 s (MAE) | Description (mean judge) |",
        "|---|---|---|---|---|---|---|",
    ]
    for model, block in summary["by_model"].items():
        f = block["primary_fields"]
        lines.append(
            f"| `{model}` | {block['num_model_outputs']} of {block['num_attempted']} "
            f"| {_fmt(f['type']['accuracy_pct'], 1, '%')} | {_fmt(f['severity_level']['accuracy_pct'], 1, '%')} "
            f"| {_fmt(f['start_timestamp']['tolerance_accuracy_pct'], 1, '%')} ({_fmt(f['start_timestamp']['mean_abs_error_s'], 2, ' s')}) "
            f"| {_fmt(f['end_timestamp']['tolerance_accuracy_pct'], 1, '%')} ({_fmt(f['end_timestamp']['mean_abs_error_s'], 2, ' s')}) "
            f"| {_fmt(f['description']['mean_judge_score'], 3)} |"
        )
    lines += [
        "",
        "## Processing time by model (successful P1 HTTP round trip; no waiting included)",
        "",
        "| Model | n | Mean | Median | p90 | Min | Max | Failed calls | Mean completion tokens |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for model, block in summary["by_model"].items():
        t = block["processing_time_s"]
        failed = len([1 for f in block["failures"] if f["outcome"] in ("timeout", "rate_limited", "http_error")])
        lines.append(
            f"| `{model}` | {t['n']} | {_fmt(t['mean'], 1, ' s')} | {_fmt(t['median'], 1, ' s')} | {_fmt(t['p90'], 1, ' s')} "
            f"| {_fmt(t['min'], 1, ' s')} | {_fmt(t['max'], 1, ' s')} | {failed} | {_fmt(block['completion_tokens']['mean'], 0)} |"
        )
    lines += [
        "",
        "## Diagnostics (not headline metrics)",
        "",
        "| Model | Contract-valid | Contract-invalid | Parse failures | Timeouts | Rate-limited (final) | HTTP failures "
        "| Not attempted | 429 retries | Derived duration ±5 s (MAE) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model, block in summary["by_model"].items():
        o, d = block["outcomes"], block["derived_diagnostics"]["duration"]
        lines.append(
            f"| `{model}` | {block['num_contract_valid']} | {o['contract_invalid']} | {o['parse_failure']} | {o['timeout']} "
            f"| {o['rate_limited']} | {o['http_error']} | {o['not_attempted']} | {block['rate_limit']['retries']} "
            f"| {_fmt(d['tolerance_accuracy_pct'], 1, '%')} ({_fmt(d['mean_abs_error_s'], 2, ' s')}) |"
        )
    lines += ["", "## Notes", ""]
    lines += [f"- **{name}:** {text}" for name, text in summary["metric_definitions"].items()]
    lines += [f"- `{model}`: {note}" for model, note in summary["model_notes"].items()]
    if summary["missing_videos_by_model"]:
        lines.append(f"- Videos missing for some models: {summary['missing_videos_by_model']}")
    return "\n".join(lines) + "\n"


def write_outputs(rows: list[dict], summary: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    def write_csv(name: str, columns: list[str], data: list[dict]) -> None:
        path = out_dir / name
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(data)
        paths.append(path)

    write_csv("benchmark_per_video.csv", PER_VIDEO_COLUMNS, rows)
    by_model = [flat_summary_row(block, model_id=m) for m, block in summary["by_model"].items()]
    write_csv("benchmark_by_model.csv", list(by_model[0]) if by_model else ["model_id"], by_model)
    by_cat = [flat_summary_row(block, category=c, model_id=m)
              for c, models in summary["by_category_and_model"].items() for m, block in models.items()]
    write_csv("benchmark_by_category_and_model.csv", list(by_cat[0]) if by_cat else ["category", "model_id"], by_cat)
    json_path = out_dir / "benchmark_by_model.json"
    json_path.write_text(json.dumps(summary, indent=2))
    md_path = out_dir / "benchmark_by_model.md"
    md_path.write_text(markdown(summary))
    return [*paths, json_path, md_path]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=None, help="One run under eval_data/results/runs/ (default: newest).")
    args = parser.parse_args()
    run_dir = args.run_dir or newest_run_dir()
    payloads = load_run(run_dir)
    rows = build_rows(payloads, load_dataset_videos())
    summary = build_summary(rows, payloads, run_dir)
    for path in write_outputs(rows, summary, RESULTS_DIR / "benchmark" / run_dir.name):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
