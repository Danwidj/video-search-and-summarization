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

"""Phase 0 gate of ``.docs/prompt-contract-plan.md``: can each model run the shared contract?

For every model, four checks against the real gateway:

1. ``schema_enforced`` - text-only call whose ``response_format`` schema allows
   exactly ``{"answer_code": "schema-enforced"}`` while the prompt asks for
   free prose. Only real server-side enforcement produces that object; a model
   that merely "tends to return JSON" fails.
2. ``url_fetch`` - one sentence about the video, sent as a signed R2 URL.
3. ``url_negative_control`` - the same call with a signed URL for an object
   that does not exist. The server must reject it; if it answers anyway, the
   model is not actually reading the URL and check 2 proves nothing.
4. ``p1_contract`` - the real P1 call (video URL first, then the shared
   prompt, strict ``response_format``) parsed with ``contract.parse_report``.

A model passes only if all four pass. Results go to stdout and to
``eval_data/probe/probe_<UTC timestamp>.json``; the exit code is 1 if any model
fails. Cost: 4 calls per model (2 carry the video).

Every check also records ``finish_reason``, token ``usage`` and the length of
``reasoning_content``, and a valid P1 check stores the full report, so both an
empty answer and a wrong-but-valid answer can be diagnosed.

Optional, not part of the verdict:
- ``--compare-base64`` adds ``p1_contract_base64``: the same P1 call with the
  video inlined as base64 (the pre-contract eval input), to tell URL effects
  from model effects.
- ``--p1-max-tokens N`` raises the P1 token budget, to test whether a reasoning
  model runs out of tokens before emitting the JSON.

Usage (from ``eval/``):
    uv run python scripts/probe_structured_output.py --video-key anomaly/assault/<clip>.mp4
    uv run python scripts/probe_structured_output.py --models nvidia/cosmos-3-nano-reasoner
    uv run python scripts/probe_structured_output.py --video-key <key> --compare-base64 --p1-max-tokens 16384
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402,F401 - loads .env.local before R2 settings are read
import contract  # noqa: E402
from eval_vlm_client import MODELS, ChatResult, chat_completion  # noqa: E402

# Every model the plan puts on the contract: the eval set, the console default
# (VLM_MODEL, cosmos-3-nano-reasoner) and the agent VLM (cosmos-3-super-reasoner)
# - the latter two are already in MODELS.
DEFAULT_MODELS = list(dict.fromkeys(MODELS))
PROBE_DIR = Path(__file__).resolve().parents[1] / "eval_data" / "probe"
URL_TTL_SECONDS = 3600

ENFORCEMENT_EXPECTED = {"answer_code": "schema-enforced"}
ENFORCEMENT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "enforcement_probe",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"answer_code": {"type": "string", "enum": ["schema-enforced"]}},
            "required": ["answer_code"],
        },
    },
}
ENFORCEMENT_PROMPT = (
    "Write three sentences of plain prose about the history of bicycles. "
    "Do not use JSON, lists or code."
)
URL_FETCH_PROMPT = "In one sentence, describe what happens in this video."
GATE_CHECKS = ["schema_enforced", "url_fetch", "url_negative_control", "p1_contract"]
# Reported but excluded from the verdict: the same P1 call with the video inlined
# as base64 (the pre-contract eval input), to separate URL effects from model effects.
INFORMATIONAL_CHECKS = {"p1_contract_base64"}


@dataclass
class Check:
    passed: bool
    detail: str
    status_code: int | None = None
    content_preview: str = ""
    # Diagnostics copied from the response: why a reasoning model returned no
    # content (finish_reason "length" + large reasoning), and the full P1 report
    # so answer quality - not just shape - can be reviewed.
    finish_reason: str | None = None
    usage: dict = field(default_factory=dict)
    reasoning_chars: int = 0
    report: dict | None = None


@dataclass
class ModelResult:
    model: str
    checks: dict[str, Check] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        gate = [c for name, c in self.checks.items() if name not in INFORMATIONAL_CHECKS]
        return bool(gate) and all(c.passed for c in gate)


def _preview(text: str | None, limit: int = 300) -> str:
    return (text or "")[:limit]


def _video_messages(url: str, text: str) -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "video_url", "video_url": {"url": url}},
                {"type": "text", "text": text},
            ],
        }
    ]


def _leaks_reasoning(content: str | None) -> bool:
    return (content or "").lstrip().lower().startswith("<think")


def check_schema_enforced(result: ChatResult) -> Check:
    if not result.ok:
        return Check(False, f"request failed: {result.error}", result.status_code)
    try:
        decoded = json.loads(result.content or "")
    except json.JSONDecodeError:
        return Check(False, "content is not JSON - response_format ignored", result.status_code, _preview(result.content))
    if decoded != ENFORCEMENT_EXPECTED:
        return Check(False, f"JSON does not match the enforced schema: {decoded!r}", result.status_code)
    return Check(True, "server-side schema enforcement confirmed", result.status_code)


def check_url_fetch(result: ChatResult) -> Check:
    if not result.ok:
        return Check(False, f"request failed: {result.error}", result.status_code)
    if not (result.content or "").strip():
        return Check(False, "empty content", result.status_code)
    return Check(True, "answered with the signed URL", result.status_code, _preview(result.content))


def check_url_negative_control(result: ChatResult) -> Check:
    if not result.ok:
        return Check(True, "missing object rejected as expected", result.status_code, _preview(result.error))
    return Check(
        False,
        "server answered for a missing object - the model may not be reading the URL, so url_fetch is unverified",
        result.status_code,
        _preview(result.content),
    )


def check_p1_contract(result: ChatResult) -> Check:
    if not result.ok:
        return Check(False, f"request failed: {result.error}", result.status_code)
    if _leaks_reasoning(result.content):
        return Check(False, "reasoning text leaked into content", result.status_code, _preview(result.content))
    try:
        report = contract.parse_report(result.content)
    except contract.ContractError as exc:
        return Check(False, str(exc), result.status_code, _preview(result.content))
    incident = report["incident"]
    return Check(
        True,
        f"valid: type={incident['type']!r} severity={incident['severity_level']} "
        f"entities={len(report['entities'])} timeline={len(report['timeline'])}",
        result.status_code,
        report=report,
    )


def with_diagnostics(check: Check, result: ChatResult) -> Check:
    check.finish_reason = result.finish_reason
    check.usage = (result.raw or {}).get("usage") or {}
    check.reasoning_chars = len(result.reasoning_content or "")
    return check


def probe_model(
    model: str,
    video_url: str,
    missing_url: str,
    *,
    base64_url: str | None = None,
    p1_max_tokens: int | None = None,
) -> ModelResult:
    result = ModelResult(model)

    def run(check_fn, messages, response_format=None, max_tokens=None):
        overrides = {}
        if response_format is not None:
            overrides["response_format"] = response_format
        if max_tokens is not None:
            overrides["max_tokens"] = max_tokens
        response = chat_completion(model, messages, inference_config=overrides or None)
        return with_diagnostics(check_fn(response), response)

    result.checks["schema_enforced"] = run(
        check_schema_enforced, [{"role": "user", "content": ENFORCEMENT_PROMPT}], ENFORCEMENT_RESPONSE_FORMAT
    )
    result.checks["url_fetch"] = run(check_url_fetch, _video_messages(video_url, URL_FETCH_PROMPT))
    result.checks["url_negative_control"] = run(
        check_url_negative_control, _video_messages(missing_url, URL_FETCH_PROMPT)
    )
    p1_prompt = contract.extraction_prompt()
    result.checks["p1_contract"] = run(
        check_p1_contract, _video_messages(video_url, p1_prompt), contract.response_format(), p1_max_tokens
    )
    if base64_url is not None:
        result.checks["p1_contract_base64"] = run(
            check_p1_contract, _video_messages(base64_url, p1_prompt), contract.response_format(), p1_max_tokens
        )
    return result


def _r2_client():
    # Imported lazily: r2_videos pulls in streamlit and boto3, which the hermetic
    # tests of this module do not need.
    import r2_videos

    if not r2_videos.configured():
        raise SystemExit("R2 is not configured: set R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET in .env.local")
    return r2_videos.client()


def signed_url(client, key: str) -> str:
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": key, "ResponseContentDisposition": "inline"},
        ExpiresIn=URL_TTL_SECONDS,
    )


def first_video_key(client, prefix: str) -> str:
    response = client.list_objects_v2(Bucket=os.environ["R2_BUCKET"], Prefix=prefix, MaxKeys=50)
    for item in response.get("Contents", []):
        if item["Key"].lower().endswith(".mp4") and item.get("Size", 0) > 0:
            return item["Key"]
    raise SystemExit(f"no .mp4 object under {prefix!r}; pass --video-key")


def print_table(results: list[ModelResult]) -> None:
    names = GATE_CHECKS + sorted({n for r in results for n in r.checks if n in INFORMATIONAL_CHECKS})
    print(f"\n{'model':48} " + " ".join(f"{n:20}" for n in names) + " verdict")
    for r in results:
        cells = " ".join(f"{('PASS' if n in r.checks and r.checks[n].passed else 'FAIL'):20}" for n in names)
        print(f"{r.model:48} {cells} {'PASS' if r.passed else 'FAIL'}")
    for r in results:
        for name, check in r.checks.items():
            extra = f" (finish_reason={check.finish_reason}, reasoning_chars={check.reasoning_chars})"
            if not check.passed:
                print(f"  {r.model} / {name}: {check.detail}{extra}")
            elif check.report is not None:
                print(f"  {r.model} / {name}: {check.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--video-key", help="R2 key of a short clip (default: first .mp4 under --prefix)")
    parser.add_argument("--prefix", default="anomaly/")
    parser.add_argument(
        "--compare-base64",
        action="store_true",
        help="also run P1 with the video inlined as base64 (informational, not part of the verdict)",
    )
    parser.add_argument(
        "--p1-max-tokens", type=int, help="override max_tokens for the P1 calls only (default: the fixed 4096)"
    )
    args = parser.parse_args(argv)

    client = _r2_client()
    video_key = args.video_key or first_video_key(client, args.prefix)
    video_url = signed_url(client, video_key)
    missing_url = signed_url(client, f"probe-missing/{uuid.uuid4()}.mp4")
    base64_url = None
    if args.compare_base64:
        response = client.get_object(Bucket=os.environ["R2_BUCKET"], Key=video_key)
        base64_url = "data:video/mp4;base64," + base64.b64encode(response["Body"].read()).decode()
    print(f"contract {contract.contract_version()} | video {video_key} | models {len(args.models)}")

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = PROBE_DIR / f"probe_{stamp}.json"

    results: list[ModelResult] = []
    for model in args.models:
        print(f"probing {model} ...", flush=True)
        try:
            results.append(
                probe_model(model, video_url, missing_url, base64_url=base64_url, p1_max_tokens=args.p1_max_tokens)
            )
        except Exception as exc:  # keep probing the other models; record why this one stopped
            failed = ModelResult(model)
            failed.checks["probe_error"] = Check(False, f"{type(exc).__name__}: {exc}")
            results.append(failed)
        # Saved after every model so an interrupted run keeps what finished.
        write_results(out_path, video_key, stamp, results, args.p1_max_tokens)
    print_table(results)
    print(f"\nwrote {out_path}")
    return 0 if all(r.passed for r in results) else 1


_SIGNED_QUERY = re.compile(r"(X-Amz-(?:Signature|Credential|Security-Token))=[^&\s\"']+")


def redact(text: str) -> str:
    """Strip presigned-URL credentials so the saved JSON is safe to share."""
    return _SIGNED_QUERY.sub(r"\1=REDACTED", text)


def write_results(
    out_path: Path, video_key: str, stamp: str, results: list[ModelResult], p1_max_tokens: int | None = None
) -> None:
    payload = {
        "contract_version": contract.contract_version(),
        "video_key": video_key,
        "run_at": stamp,
        "p1_max_tokens": p1_max_tokens,
        "results": [
            {"model": r.model, "passed": r.passed, "checks": {k: asdict(v) for k, v in r.checks.items()}}
            for r in results
        ],
    }
    out_path.write_text(redact(json.dumps(payload, indent=2)))


if __name__ == "__main__":
    raise SystemExit(main())
