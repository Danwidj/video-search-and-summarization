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

Usage (from ``eval/``):
    uv run python scripts/probe_structured_output.py --video-key anomaly/assault/<clip>.mp4
    uv run python scripts/probe_structured_output.py --models nvidia/cosmos-3-nano-reasoner
"""

from __future__ import annotations

import argparse
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


@dataclass
class Check:
    passed: bool
    detail: str
    status_code: int | None = None
    content_preview: str = ""


@dataclass
class ModelResult:
    model: str
    checks: dict[str, Check] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks.values())


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
    )


def probe_model(model: str, video_url: str, missing_url: str) -> ModelResult:
    result = ModelResult(model)
    result.checks["schema_enforced"] = check_schema_enforced(
        chat_completion(
            model,
            [{"role": "user", "content": ENFORCEMENT_PROMPT}],
            inference_config={"response_format": ENFORCEMENT_RESPONSE_FORMAT},
        )
    )
    result.checks["url_fetch"] = check_url_fetch(chat_completion(model, _video_messages(video_url, URL_FETCH_PROMPT)))
    result.checks["url_negative_control"] = check_url_negative_control(
        chat_completion(model, _video_messages(missing_url, URL_FETCH_PROMPT))
    )
    result.checks["p1_contract"] = check_p1_contract(
        chat_completion(
            model,
            _video_messages(video_url, contract.extraction_prompt()),
            inference_config={"response_format": contract.response_format()},
        )
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
    names = ["schema_enforced", "url_fetch", "url_negative_control", "p1_contract"]
    print(f"\n{'model':48} " + " ".join(f"{n:20}" for n in names) + " verdict")
    for r in results:
        cells = " ".join(f"{('PASS' if n in r.checks and r.checks[n].passed else 'FAIL'):20}" for n in names)
        print(f"{r.model:48} {cells} {'PASS' if r.passed else 'FAIL'}")
    for r in results:
        for name, check in r.checks.items():
            if not check.passed:
                print(f"  {r.model} / {name}: {check.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--video-key", help="R2 key of a short clip (default: first .mp4 under --prefix)")
    parser.add_argument("--prefix", default="anomaly/")
    args = parser.parse_args(argv)

    client = _r2_client()
    video_key = args.video_key or first_video_key(client, args.prefix)
    video_url = signed_url(client, video_key)
    missing_url = signed_url(client, f"probe-missing/{uuid.uuid4()}.mp4")
    print(f"contract {contract.contract_version()} | video {video_key} | models {len(args.models)}")

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = PROBE_DIR / f"probe_{stamp}.json"

    results: list[ModelResult] = []
    for model in args.models:
        print(f"probing {model} ...", flush=True)
        try:
            results.append(probe_model(model, video_url, missing_url))
        except Exception as exc:  # keep probing the other models; record why this one stopped
            failed = ModelResult(model)
            failed.checks["probe_error"] = Check(False, f"{type(exc).__name__}: {exc}")
            results.append(failed)
        # Saved after every model so an interrupted run keeps what finished.
        write_results(out_path, video_key, stamp, results)
    print_table(results)
    print(f"\nwrote {out_path}")
    return 0 if all(r.passed for r in results) else 1


_SIGNED_QUERY = re.compile(r"(X-Amz-(?:Signature|Credential|Security-Token))=[^&\s\"']+")


def redact(text: str) -> str:
    """Strip presigned-URL credentials so the saved JSON is safe to share."""
    return _SIGNED_QUERY.sub(r"\1=REDACTED", text)


def write_results(out_path: Path, video_key: str, stamp: str, results: list[ModelResult]) -> None:
    payload = {
        "contract_version": contract.contract_version(),
        "video_key": video_key,
        "run_at": stamp,
        "results": [
            {"model": r.model, "passed": r.passed, "checks": {k: asdict(v) for k, v in r.checks.items()}}
            for r in results
        ],
    }
    out_path.write_text(redact(json.dumps(payload, indent=2)))


if __name__ == "__main__":
    raise SystemExit(main())
