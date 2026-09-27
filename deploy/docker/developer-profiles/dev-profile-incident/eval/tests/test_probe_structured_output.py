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

"""Phase 0 probe verdict logic, with the gateway mocked (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import probe_structured_output as probe  # noqa: E402
from eval_vlm_client import ChatResult  # noqa: E402
from test_contract import _valid_report  # noqa: E402

GOOD = "https://r2.example/video.mp4?sig"
MISSING = "https://r2.example/missing.mp4?sig"


def _fake_gateway(*, enforced=True, fetches=True, rejects_missing=True, p1_content=None):
    calls = []

    def fake(model, messages, *, inference_config=None, timeout=240.0):
        calls.append({"model": model, "messages": messages, "inference_config": inference_config})
        fmt = (inference_config or {}).get("response_format")
        content = messages[0]["content"]
        if isinstance(content, str):  # enforcement probe
            if enforced:
                return ChatResult(ok=True, content=json.dumps(probe.ENFORCEMENT_EXPECTED), status_code=200)
            return ChatResult(ok=True, content="Bicycles were invented in the 19th century.", status_code=200)
        url = content[0]["video_url"]["url"]
        if url == MISSING:
            if rejects_missing:
                return ChatResult(ok=False, error="failed to fetch video", status_code=400)
            return ChatResult(ok=True, content="A person walks down a street.", status_code=200)
        if not fetches:
            return ChatResult(ok=False, error="unsupported url", status_code=400)
        if fmt is None:
            return ChatResult(ok=True, content="Two people fight in a shop.", status_code=200)
        return ChatResult(ok=True, content=p1_content or json.dumps(_valid_report()), status_code=200)

    return fake, calls


def test_all_checks_pass(monkeypatch):
    fake, calls = _fake_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    result = probe.probe_model("m", GOOD, MISSING)
    assert result.passed, {k: v.detail for k, v in result.checks.items()}
    assert len(calls) == 4


def test_p1_call_puts_video_first_and_sends_strict_contract(monkeypatch):
    fake, calls = _fake_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    probe.probe_model("m", GOOD, MISSING)
    p1 = calls[-1]
    parts = p1["messages"][0]["content"]
    assert parts[0]["type"] == "video_url" and parts[0]["video_url"]["url"] == GOOD
    assert parts[1]["type"] == "text" and "UNIFIED VLM INCIDENT EXTRACTION PROMPT" in parts[1]["text"]
    fmt = p1["inference_config"]["response_format"]
    assert fmt["json_schema"]["name"] == "incident_report" and fmt["json_schema"]["strict"] is True


def test_unenforced_schema_fails(monkeypatch):
    fake, _ = _fake_gateway(enforced=False)
    monkeypatch.setattr(probe, "chat_completion", fake)
    result = probe.probe_model("m", GOOD, MISSING)
    assert not result.passed
    assert not result.checks["schema_enforced"].passed


def test_model_answering_for_missing_object_fails_negative_control(monkeypatch):
    fake, _ = _fake_gateway(rejects_missing=False)
    monkeypatch.setattr(probe, "chat_completion", fake)
    result = probe.probe_model("m", GOOD, MISSING)
    assert result.checks["url_fetch"].passed
    assert not result.checks["url_negative_control"].passed
    assert not result.passed


def test_url_rejected_fails_fetch_and_p1(monkeypatch):
    fake, _ = _fake_gateway(fetches=False)
    monkeypatch.setattr(probe, "chat_completion", fake)
    result = probe.probe_model("m", GOOD, MISSING)
    assert not result.checks["url_fetch"].passed
    assert not result.checks["p1_contract"].passed


def test_fenced_or_reasoning_p1_output_fails(monkeypatch):
    for content in ("```json\n" + json.dumps(_valid_report()) + "\n```", "<think>hmm</think>" + json.dumps(_valid_report())):
        fake, _ = _fake_gateway(p1_content=content)
        monkeypatch.setattr(probe, "chat_completion", fake)
        assert not probe.probe_model("m", GOOD, MISSING).checks["p1_contract"].passed


def test_invalid_p1_json_fails_with_contract_error(monkeypatch):
    bad = _valid_report()
    bad["incident"]["type"] = "fighting"
    fake, _ = _fake_gateway(p1_content=json.dumps(bad))
    monkeypatch.setattr(probe, "chat_completion", fake)
    check = probe.probe_model("m", GOOD, MISSING).checks["p1_contract"]
    assert not check.passed and "schema violation" in check.detail


def test_main_saves_after_each_model_and_survives_a_crash(monkeypatch, tmp_path):
    fake, _ = _fake_gateway()

    def crashing(model, *args, **kwargs):
        if model == "boom":
            raise RuntimeError("gateway exploded")
        return fake(model, *args, **kwargs)

    class _Client:
        def generate_presigned_url(self, *_args, Params, **_kwargs):
            return MISSING if Params["Key"].startswith("probe-missing/") else GOOD

    monkeypatch.setenv("R2_BUCKET", "bucket")
    monkeypatch.setattr(probe, "chat_completion", crashing)
    monkeypatch.setattr(probe, "_r2_client", lambda: _Client())
    monkeypatch.setattr(probe, "PROBE_DIR", tmp_path)

    assert probe.main(["--models", "good", "boom", "--video-key", "anomaly/x.mp4"]) == 1
    [out] = tmp_path.glob("probe_*.json")
    saved = json.loads(out.read_text())
    assert [r["model"] for r in saved["results"]] == ["good", "boom"]
    assert saved["results"][0]["passed"] is True
    assert "gateway exploded" in saved["results"][1]["checks"]["probe_error"]["detail"]


def test_redact_strips_presigned_credentials():
    url = "https://x.r2.dev/k.mp4?X-Amz-Algorithm=AWS4&X-Amz-Credential=AKIA%2F1&X-Amz-Signature=abc123&X-Amz-Expires=3600"
    out = probe.redact(f"failed to fetch {url}")
    assert "abc123" not in out and "AKIA" not in out
    assert "X-Amz-Signature=REDACTED" in out and "X-Amz-Expires=3600" in out


def test_base64_check_is_informational_and_sent_inline(monkeypatch):
    fake, calls = _fake_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    b64 = "data:video/mp4;base64,AAAA"
    result = probe.probe_model("m", GOOD, MISSING, base64_url=b64, max_tokens=16384)
    assert result.checks["p1_contract_base64"].passed
    assert calls[-1]["messages"][0]["content"][0]["video_url"]["url"] == b64
    assert calls[-1]["inference_config"]["max_tokens"] == 16384
    result.checks["p1_contract_base64"].passed = False
    assert result.passed  # base64 A/B never changes the verdict


def test_diagnostics_record_token_exhaustion(monkeypatch):
    def fake(model, messages, *, inference_config=None, timeout=240.0):
        if (inference_config or {}).get("response_format", {}).get("json_schema", {}).get("name") == "incident_report":
            return ChatResult(
                ok=True,
                content="",
                reasoning_content="x" * 9000,
                finish_reason="length",
                raw={"usage": {"completion_tokens": 4096}},
                status_code=200,
            )
        return _fake_gateway()[0](model, messages, inference_config=inference_config)

    monkeypatch.setattr(probe, "chat_completion", fake)
    check = probe.probe_model("m", GOOD, MISSING).checks["p1_contract"]
    assert not check.passed
    assert check.finish_reason == "length"
    assert check.reasoning_chars == 9000
    assert check.usage == {"completion_tokens": 4096}


def test_valid_p1_stores_full_report(monkeypatch):
    fake, _ = _fake_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    check = probe.probe_model("m", GOOD, MISSING).checks["p1_contract"]
    assert check.report == _valid_report()


def _sampling_gateway(*, validates=True, frames_matter=True):
    base, calls = _fake_gateway()

    def fake(model, messages, *, inference_config=None, timeout=240.0):
        media = (inference_config or {}).get("media_io_kwargs")
        video = (media or {}).get("video", {})
        if media is not None and "response_format" not in (inference_config or {}):
            calls.append({"model": model, "messages": messages, "inference_config": inference_config})
            if validates and (("fps" in video and "num_frames" in video) or video.get("fps", 0) > 60):
                return ChatResult(ok=False, error="400 invalid media_io_kwargs", status_code=400)
            if "num_frames" in video and frames_matter:
                return ChatResult(ok=True, content=f"seen with {video['num_frames']} frames", status_code=200)
            return ChatResult(ok=True, content="A person walks.", status_code=200)
        return base(model, messages, inference_config=inference_config)

    return fake, calls


def test_sampling_tests_detect_forwarding_and_effect(monkeypatch):
    fake, _ = _sampling_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    result = probe.probe_model("m", GOOD, MISSING, sampling_tests=True)
    assert result.checks["sampling_conflict"].passed
    assert result.checks["sampling_overlimit"].passed
    assert "takes effect" in result.checks["sampling_frames_8"].detail
    assert result.passed  # informational checks never change the verdict


def test_sampling_tests_detect_dropped_or_ignored_field(monkeypatch):
    fake, _ = _sampling_gateway(validates=False, frames_matter=False)
    monkeypatch.setattr(probe, "chat_completion", fake)
    result = probe.probe_model("m", GOOD, MISSING, sampling_tests=True)
    assert not result.checks["sampling_conflict"].passed
    assert "dropped" in result.checks["sampling_overlimit"].detail
    assert "may be ignored" in result.checks["sampling_frames_64"].detail
    assert result.passed


def test_media_io_kwargs_sent_only_with_real_video(monkeypatch):
    fake, calls = _fake_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    media = {"video": {"fps": 4.0}}
    probe.probe_model("m", GOOD, MISSING, base64_url="data:video/mp4;base64,AA", media_io_kwargs=media)
    by_url = [
        (c["messages"][0]["content"][0]["video_url"]["url"] if isinstance(c["messages"][0]["content"], list) else None,
         (c["inference_config"] or {}).get("media_io_kwargs"))
        for c in calls
    ]
    assert by_url[0] == (None, None)  # enforcement probe: no video
    assert (MISSING, None) in by_url  # negative control stays untouched
    assert [m for u, m in by_url if u == GOOD] == [media, media]  # url_fetch + p1
    assert by_url[-1] == ("data:video/mp4;base64,AA", media)


def test_max_tokens_applies_to_every_call(monkeypatch):
    fake, calls = _fake_gateway()
    monkeypatch.setattr(probe, "chat_completion", fake)
    probe.probe_model("m", GOOD, MISSING, max_tokens=16384)
    assert len(calls) == 4
    assert all((c["inference_config"] or {}).get("max_tokens") == 16384 for c in calls)
