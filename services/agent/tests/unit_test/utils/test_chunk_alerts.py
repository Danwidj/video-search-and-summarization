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

"""Unit tests for the alert rules per chunk: the rules file, the one alert call and the defensive answer parser.

The timeline is built from the recorded IMG_8206 captions (``fixtures/chunk_captions_img8206_w20.json``) the way
the caption pass builds it; the model answers are fakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from vss_agents import incident_contract
from vss_agents.utils.chunk_alerts import RULES_FILE
from vss_agents.utils.chunk_alerts import AlertRule
from vss_agents.utils.chunk_alerts import ChunkAlertError
from vss_agents.utils.chunk_alerts import alert_request_body
from vss_agents.utils.chunk_alerts import alerts_enabled
from vss_agents.utils.chunk_alerts import check_alerts
from vss_agents.utils.chunk_alerts import load_rules
from vss_agents.utils.chunk_alerts import parse_alert_answer
from vss_agents.utils.chunk_captions import clean_caption
from vss_agents.utils.chunk_captions import filter_short_duration_lines
from vss_agents.utils.chunk_captions import offset_chunk_timestamps
from vss_agents.utils.chunk_captions import parse_caption_events

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "chunk_captions_img8206_w20.json").read_text())


def _timeline() -> list[dict]:
    timeline = []
    for chunk in FIXTURE["chunks"]:
        caption = filter_short_duration_lines(
            offset_chunk_timestamps(clean_caption(chunk["content"]), chunk["start"], chunk["end"])
        )
        timeline.append(
            {"start": chunk["start"], "end": chunk["end"], "caption": caption, "events": parse_caption_events(caption)}
        )
    return timeline


TIMELINE = _timeline()
RULES = [
    AlertRule("person-falls", "A person falls to the ground or is lying on the floor."),
    AlertRule("unattended-bag-picked-up", "An unattended bag left on the floor is picked up."),
]


def _answer(*rules: dict) -> str:
    return json.dumps({"rules": list(rules)})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRulesFile:
    def test_the_shipped_rules_load(self):
        rules = load_rules()
        assert 3 <= len(rules) <= 5
        assert {"person-falls", "unattended-bag-picked-up", "person-carried-or-dragged"} <= {r.id for r in rules}
        assert all(rule.text for rule in rules)

    @pytest.mark.parametrize(
        ("content", "reason"),
        [
            ("not json", "unreadable"),
            ("[]", "non-empty list"),
            ('{"id": "a", "text": "b"}', "non-empty list"),
            ('[{"id": "Bad Id", "text": "x"}]', "needs an id"),
            ('[{"id": "a", "text": "  "}]', "has no text"),
            ('[{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]', "appears twice"),
        ],
    )
    def test_a_malformed_file_is_a_plain_reason(self, tmp_path, content, reason):
        path = tmp_path / "rules.json"
        path.write_text(content)
        with pytest.raises(ChunkAlertError, match=reason):
            load_rules(path)

    def test_a_missing_file_is_a_plain_reason(self, tmp_path):
        with pytest.raises(ChunkAlertError, match="unreadable"):
            load_rules(tmp_path / "absent.json")

    def test_the_default_path_sits_beside_the_module(self):
        assert RULES_FILE.name == "chunk_alert_rules.json" and RULES_FILE.exists()


class TestFlag:
    def test_off_by_default_and_only_the_literal_1_enables(self, monkeypatch):
        monkeypatch.delenv("INCIDENT_ALERTS_ENABLED", raising=False)
        assert alerts_enabled() is False
        monkeypatch.setenv("INCIDENT_ALERTS_ENABLED", "true")
        assert alerts_enabled() is False
        monkeypatch.setenv("INCIDENT_ALERTS_ENABLED", "1")
        assert alerts_enabled() is True


class TestRequest:
    def test_one_text_call_with_every_rule_and_every_window_on_the_rp1_model(self):
        body = alert_request_body(TIMELINE, RULES)
        settings = incident_contract.rp1_request()
        assert body["model"] == settings["model"] and body["temperature"] == settings["temperature"]
        assert body["chat_template_kwargs"] == settings["chat_template_kwargs"]
        prompt = body["messages"][1]["content"]
        assert all(f"- {rule.id}: {rule.text}" in prompt for rule in RULES)
        for index, entry in enumerate(TIMELINE):
            assert f"[{index}] {entry['start']:.1f}s-{entry['end']:.1f}s\n{entry['caption']}" in prompt
        assert not any(isinstance(m["content"], list) for m in body["messages"])  # text only, no video


class TestParse:
    def test_a_match_carries_the_rule_text_and_the_window_bounds(self):
        alerts = parse_alert_answer(
            _answer(
                {"rule_id": "person-falls", "matches": [{"window": 5, "reason": "A man is lying on the floor."}]},
                {"rule_id": "unattended-bag-picked-up", "matches": []},
            ),
            TIMELINE,
            RULES,
        )
        assert alerts == [
            {
                "rule_id": "person-falls",
                "rule": RULES[0].text,
                "window_index": 5,
                "start": 90.0,
                "end": 94.194,
                "reason": "A man is lying on the floor.",
            }
        ]

    def test_no_match_is_an_empty_list(self):
        answer = _answer({"rule_id": "person-falls", "matches": []}, {"rule_id": "unattended-bag-picked-up"})
        assert parse_alert_answer(answer, TIMELINE, RULES) == []

    def test_ordered_by_window_then_rule_and_deduplicated(self):
        alerts = parse_alert_answer(
            _answer(
                {"rule_id": "unattended-bag-picked-up", "matches": [{"window": 4, "reason": "picked up"}]},
                {
                    "rule_id": "person-falls",
                    "matches": [{"window": 5, "reason": "lying"}, {"window": 4, "reason": "falls"}, {"window": 4}],
                },
            ),
            TIMELINE,
            RULES,
        )
        assert [(a["window_index"], a["rule_id"], a["reason"]) for a in alerts] == [
            (4, "person-falls", "falls"),
            (4, "unattended-bag-picked-up", "picked up"),
            (5, "person-falls", "lying"),
        ]

    def test_unknown_rules_and_windows_outside_the_timeline_are_ignored_not_repaired(self):
        alerts = parse_alert_answer(
            _answer(
                {"rule_id": "made-up", "matches": [{"window": 1, "reason": "x"}]},
                {
                    "rule_id": "person-falls",
                    "matches": [
                        {"window": 6, "reason": "past the end"},
                        {"window": -1, "reason": "negative"},
                        {"window": True, "reason": "bool"},
                        {"window": 1.5, "reason": "fraction"},
                        "not a match",
                        {"window": "4", "reason": "  spaced\n  reason  "},
                    ],
                },
                "not a rule",
            ),
            TIMELINE,
            RULES,
        )
        assert [(a["window_index"], a["reason"]) for a in alerts] == [(4, "spaced reason")]

    def test_a_fenced_or_thinking_answer_is_read(self):
        answer = (
            "<think>looking</think>```json\n"
            + _answer({"rule_id": "person-falls", "matches": [{"window": 5}]})
            + "\n```"
        )
        alerts = parse_alert_answer(answer, TIMELINE, RULES)
        assert [(a["window_index"], a["reason"]) for a in alerts] == [(5, "")]

    def test_json_inside_prose_is_read(self):
        answer = (
            "Here you go: " + _answer({"rule_id": "person-falls", "matches": [{"window": 0, "reason": "r"}]}) + " Done."
        )
        assert len(parse_alert_answer(answer, TIMELINE, RULES)) == 1

    @pytest.mark.parametrize(
        ("content", "reason"),
        [
            ("I could not decide.", "not JSON"),
            ("", "not JSON"),
            ('{"rules": "none"}', "no rules list"),
            ('{"alerts": []}', "no rules list"),
            ("42", "no rules list"),
        ],
    )
    def test_a_malformed_answer_raises_a_plain_reason(self, content, reason):
        with pytest.raises(ChunkAlertError, match=reason):
            parse_alert_answer(content, TIMELINE, RULES)


class TestCheckAlerts:
    @pytest.mark.asyncio
    async def test_one_call_returns_the_matches_and_telemetry(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            answer = _answer({"rule_id": "person-falls", "matches": [{"window": 5, "reason": "man lying on floor"}]})
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": answer}}],
                    "usage": {"prompt_tokens": 2100, "completion_tokens": 40},
                },
            )

        async with _client(handler) as client:
            result = await check_alerts(
                client=client, base_url="https://switchyard.example/", timeline=TIMELINE, rules=RULES
            )
        assert len(requests) == 1
        assert str(requests[0].url) == "https://switchyard.example/v1/chat/completions"
        assert [a["window_index"] for a in result.alerts] == [5]
        telemetry = dict(result.telemetry)
        assert telemetry.pop("elapsed_ms") >= 0
        assert telemetry == {
            "model": incident_contract.rp1_request()["model"],
            "rules": 2,
            "windows": 6,
            "matches": 1,
            "prompt_tokens": 2100,
            "completion_tokens": 40,
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "reason"),
        [
            (httpx.Response(429, text="slow down"), "HTTP 429"),
            (httpx.Response(200, json={"choices": []}), "no completion"),
            (httpx.Response(200, text="<html>"), "not JSON"),
            (httpx.Response(200, json={"choices": [{"message": {"content": "no idea"}}]}), "not JSON"),
        ],
    )
    async def test_failures_raise_a_plain_reason(self, response, reason):
        async with _client(lambda _request: response) as client:
            with pytest.raises(ChunkAlertError, match=reason):
                await check_alerts(client=client, base_url="https://x", timeline=TIMELINE, rules=RULES)

    @pytest.mark.asyncio
    async def test_a_transport_error_is_a_plain_reason(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        async with _client(handler) as client:
            with pytest.raises(ChunkAlertError, match="ConnectError"):
                await check_alerts(client=client, base_url="https://x", timeline=TIMELINE, rules=RULES)

    @pytest.mark.asyncio
    async def test_no_timeline_makes_no_call(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no call expected")

        async with _client(handler) as client:
            with pytest.raises(ChunkAlertError, match="no chunk timeline"):
                await check_alerts(client=client, base_url="https://x", timeline=[], rules=RULES)
