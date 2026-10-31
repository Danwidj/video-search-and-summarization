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

"""Alert rules per chunk for the incident ``/analyze`` path (after the caption pass).

A small list of natural-language rules (``chunk_alert_rules.json`` beside this module, ``[{id, text}]``) is
checked against the caption pass's window captions (``utils/chunk_captions.py``) in **one** text call to the
RP1 language model, through the same HTTP client and key the rest of ``incident_report_gen`` uses. The model
answers, per rule, the indexes of the windows whose caption matches with a one-line reason; the answer is
parsed defensively and becomes ``chunk_alerts`` ``[{rule_id, rule, window_index, start, end, reason}]``.

Everything here is best-effort for the caller: :func:`check_alerts` raises :class:`ChunkAlertError` with a plain
reason (bad rules file, HTTP error, an answer that is not the expected JSON) and ``incident_report_gen`` turns it
into ``alerting.skipped``; the analysis itself never fails because of alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import httpx

from vss_agents import incident_contract
from vss_agents.utils.chunk_captions import clean_caption

ALERTS_FLAG = "INCIDENT_ALERTS_ENABLED"
RULES_FILE = Path(__file__).with_name("chunk_alert_rules.json")
MAX_RULES = 20
MAX_REASON_CHARS = 300
_RULE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

ALERT_SYSTEM_PROMPT = "You check captions of video windows against alert rules. Answer with JSON only."

ALERT_PROMPT = """Below are alert rules and the captions of consecutive time windows of one video. A vision model
wrote the captions; they are the only evidence you have. A window matches a rule only when its caption clearly
describes the event in the rule. Do not guess: when no caption clearly describes a rule's event, that rule has no
matches. Windows overlap by a few seconds, so one event may match two neighbouring windows.

RULES
{rules}

WINDOWS (index, time range in seconds from the start of the video, then the caption)
{windows}

Answer with one JSON object and nothing else, in this form:
{{"rules": [{{"rule_id": "<rule id>", "matches": [{{"window": <window index>, "reason": "<one line: what the caption \
describes that matches the rule>"}}]}}]}}
List every rule once, with an empty matches list when no window matches it."""


class ChunkAlertError(RuntimeError):
    """The alert check could not run or its answer was unusable; the message is the ``alerting.skipped`` reason."""


@dataclass(frozen=True)
class AlertRule:
    id: str
    text: str


@dataclass
class ChunkAlerts:
    """What an alert check produced: the matches (``None`` when it was skipped) and its telemetry."""

    alerts: list[dict[str, Any]] | None
    telemetry: dict[str, Any]


def alerts_enabled() -> bool:
    return os.environ.get(ALERTS_FLAG, "") == "1"


def load_rules(path: Path = RULES_FILE) -> list[AlertRule]:
    """The rules file as :class:`AlertRule` objects; :class:`ChunkAlertError` when it is missing or malformed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChunkAlertError(f"alert rules file {path.name} is unreadable: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ChunkAlertError(f"alert rules file {path.name} must be a non-empty list of {{id, text}}")
    if len(raw) > MAX_RULES:
        raise ChunkAlertError(f"alert rules file {path.name} has {len(raw)} rules; at most {MAX_RULES} are allowed")
    rules: list[AlertRule] = []
    for position, entry in enumerate(raw):
        rule_id = entry.get("id") if isinstance(entry, dict) else None
        text = entry.get("text") if isinstance(entry, dict) else None
        if not isinstance(rule_id, str) or not _RULE_ID.match(rule_id):
            raise ChunkAlertError(f"alert rule {position} needs an id of lower-case letters, digits, '-' or '_'")
        if not isinstance(text, str) or not text.strip():
            raise ChunkAlertError(f"alert rule {rule_id} has no text")
        if any(rule.id == rule_id for rule in rules):
            raise ChunkAlertError(f"alert rule id {rule_id} appears twice")
        rules.append(AlertRule(id=rule_id, text=" ".join(text.split())))
    return rules


def alert_request_body(timeline: list[dict[str, Any]], rules: list[AlertRule]) -> dict[str, Any]:
    """The one alert call: every rule and every window caption, with the RP1 model and settings."""
    settings = incident_contract.rp1_request()
    rules_text = "\n".join(f"- {rule.id}: {rule.text}" for rule in rules)
    windows_text = "\n\n".join(
        f"[{index}] {entry['start']:.1f}s-{entry['end']:.1f}s\n{entry['caption']}"
        for index, entry in enumerate(timeline)
    )
    return {
        **settings,
        "messages": [
            {"role": "system", "content": ALERT_SYSTEM_PROMPT},
            {"role": "user", "content": ALERT_PROMPT.format(rules=rules_text, windows=windows_text)},
        ],
        "stream": False,
    }


def _json_answer(content: str) -> Any:
    """The answer's JSON value: the whole cleaned text, else its outermost ``{...}``; ``ChunkAlertError`` otherwise."""
    cleaned = clean_caption(content)
    if cleaned.startswith("json"):  # a ```json fence leaves its language tag behind
        cleaned = cleaned[4:].lstrip()
    try:
        return json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except ValueError:
                pass
    raise ChunkAlertError(f"the alert answer is not JSON: {cleaned[:120]!r}")


def _window_index(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_alert_answer(content: str, timeline: list[dict[str, Any]], rules: list[AlertRule]) -> list[dict[str, Any]]:
    """The matches in the model's answer, ordered by window then rule order.

    Raises :class:`ChunkAlertError` when the answer as a whole is unusable (not JSON, no ``rules`` list). Within a
    usable answer, an entry naming an unknown rule or a window outside the timeline is ignored, never repaired,
    and a repeated (rule, window) pair is kept once.
    """
    answer = _json_answer(content)
    entries = answer.get("rules") if isinstance(answer, dict) else answer
    if not isinstance(entries, list):
        raise ChunkAlertError("the alert answer has no rules list")
    by_id = {rule.id: (position, rule) for position, rule in enumerate(rules)}
    found: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("rule_id") not in by_id:
            continue
        position, rule = by_id[entry["rule_id"]]
        matches = entry.get("matches")
        for match in matches if isinstance(matches, list) else []:
            index = _window_index(match.get("window")) if isinstance(match, dict) else None
            if index is None or not 0 <= index < len(timeline) or (rule.id, index) in found:
                continue
            reason = match.get("reason")
            window = timeline[index]
            found[(rule.id, index)] = {
                "rule_id": rule.id,
                "rule": rule.text,
                "window_index": index,
                "start": window["start"],
                "end": window["end"],
                "reason": " ".join(reason.split())[:MAX_REASON_CHARS] if isinstance(reason, str) else "",
                "_order": (index, position),
            }
    alerts = sorted(found.values(), key=lambda alert: alert["_order"])
    for alert in alerts:
        del alert["_order"]
    return alerts


async def check_alerts(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    timeline: list[dict[str, Any]],
    rules: list[AlertRule] | None = None,
) -> ChunkAlerts:
    """One alert call over the whole timeline; raises :class:`ChunkAlertError` with a plain reason on any failure."""
    if not timeline:
        raise ChunkAlertError("no chunk timeline")
    rules = load_rules() if rules is None else rules
    body = alert_request_body(timeline, rules)
    started = time.perf_counter()
    try:
        response = await client.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=body)
    except httpx.HTTPError as exc:
        raise ChunkAlertError(f"the alert call failed: {type(exc).__name__}: {exc}") from exc
    if response.status_code >= 400:
        raise ChunkAlertError(f"the alert call returned HTTP {response.status_code}: {response.text[:200]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ChunkAlertError("the alert call returned a body that is not JSON") from exc
    if not isinstance(payload, dict) or not payload.get("choices"):
        raise ChunkAlertError("the alert call returned no completion")
    content = (payload["choices"][0].get("message") or {}).get("content") or ""
    alerts = parse_alert_answer(content, timeline, rules)
    usage = payload.get("usage") or {}
    telemetry = {
        "model": body["model"],
        "rules": len(rules),
        "windows": len(timeline),
        "matches": len(alerts),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
    }
    return ChunkAlerts(alerts=alerts, telemetry=telemetry)
