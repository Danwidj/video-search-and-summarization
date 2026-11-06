# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The routed chat pilot: the real router and prompt over frozen questions and a multi-turn set.

Runs with the agent's Python. It is an isolated process: it reads stored snapshots, serves nothing and writes only to
``--out``. Model calls need ``--live``. Without it every model-routed item is skipped, so the deterministic half costs
nothing. Video checks are forced off. Calls are sequential and paced, nothing is retried, and the run stops before a
call that could pass ``--cap``. Frozen runs are only read; a re-run skips items already answered.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from fastapi import HTTPException

from vss_agents.api import incident_chat
from vss_agents.utils import chat_routing
from vss_agents.utils import grounded_chat
from vss_agents.utils import report_answers
from vss_agents.utils import video_check

MODEL_ROUTED_CLASSES = {"incident.unanswerable", "incident.false_premise", "incident.instrument_holder"}
PACE_SECONDS = 2.0
STOP_AFTER_ERRORS = 3
# A rate limit is the shared key's load, not an answer: wait, then ask again, a bounded number of times per run.
RATE_WAIT_SECONDS = 45.0
MAX_RATE_WAITS = 20


def load_key(env_file: Path) -> None:
    values = {}
    for line in env_file.read_text().splitlines():
        match = re.match(r"\s*([A-Z0-9_]+)=(.*)", line)
        if match:
            values[match[1]] = match[2].strip().strip("\"'")
    os.environ["INCIDENT_CHAT_BASE_URL"] = values["VLM_GATEWAY_BASE_URL"]
    os.environ["INCIDENT_CHAT_API_KEY"] = values["VLM_GATEWAY_API_KEY"]


class Store:
    """The router's RevisionStore over rows already in memory."""

    def __init__(self, rows: dict[int, dict[str, Any]], official: dict[str, int] | None = None) -> None:
        self.rows, self.official = rows, official or {}

    async def get_revision(self, revision_id: int) -> dict[str, Any] | None:
        return self.rows.get(int(revision_id))

    async def get_official_revision_id(self, video_id: str) -> int | None:
        return self.official.get(str(video_id))


class Stopped(RuntimeError):
    pass


class Metered:
    """The chat model behind a cap: refuses a call that could pass it, and keeps each call's reply and usage."""

    def __init__(self, inner: Any, cap: int, used: int, live: bool) -> None:
        self.inner, self.cap, self.used, self.live = inner, cap, used, live
        self.model = getattr(inner, "model", "none")
        self.calls: list[dict[str, Any]] = []
        self.last_usage: dict[str, Any] = {}
        self.rate_waits = 0

    async def complete(self, messages: Any, schema: Any) -> dict[str, Any]:
        if not self.live:
            raise Stopped("model call without --live")
        bound = sum(len(m["content"]) for m in messages) / 3.7 + 400
        if self.used + bound > self.cap:
            raise Stopped(f"cap: used {self.used}, next call up to {round(bound)}, cap {self.cap}")
        time.sleep(PACE_SECONDS)
        started = time.perf_counter()
        reply = await self.inner.complete(messages, schema)
        self.last_usage = dict(self.inner.last_usage)
        self.used += int(self.last_usage.get("total_tokens") or 0)
        self.calls.append({"reply": reply, "usage": self.last_usage, "seconds": round(time.perf_counter() - started, 2)})
        return reply


def endpoint(store: Store, model: Metered) -> Any:
    router = incident_chat.create_incident_chat_router(revision_store=store, chat_model=model, mode="routed")
    return next(r.endpoint for r in router.routes if getattr(r, "path", "") == "/api/v1/incidents/chat")


async def ask(handler: Any, model: Metered, version: int, messages: list[dict[str, str]]) -> dict[str, Any]:
    """One request through the real route, waiting out a rate limit; what happened, however it ended."""
    while True:
        result = await _ask_once(handler, model, version, messages)
        if "rate limited" not in str(result.get("detail")):
            return result
        model.rate_waits += 1
        if model.rate_waits > MAX_RATE_WAITS:
            raise Stopped(f"still rate limited after {MAX_RATE_WAITS} waits")
        await asyncio.sleep(RATE_WAIT_SECONDS)


async def _ask_once(handler: Any, model: Metered, version: int, messages: list[dict[str, str]]) -> dict[str, Any]:
    before = len(model.calls)
    started = time.perf_counter()
    body = incident_chat.ChatRequest.model_validate({"messages": messages, "version_id": version})
    try:
        response = await handler(body)
    except HTTPException as exc:
        return {"outcome": "http_error", "status": exc.status_code, "detail": str(exc.detail)[:300], "calls": model.calls[before:]}
    dumped = response.model_dump(exclude_none=True)
    return {
        "outcome": "answered",
        "message": dumped["message"],
        "grounding": dumped.get("grounding") or {},
        "calls": model.calls[before:],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def frozen_rows(run: Path, corpus: str, questions: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reports = json.loads((run / "corpora" / f"{corpus}.json").read_text())["reports"]
    rows = [json.loads(line) for line in (run / "answers.jsonl").read_text().splitlines()]
    wanted = [r for r in rows if r["scope"] == "incident" and r["outcome"] == "answered"]
    for row in wanted:
        row["question"] = questions[row["record_id"]]["question"]
    return wanted, reports


async def run_frozen(args: argparse.Namespace, model: Metered, out: Path) -> None:
    items = [("system", args.system_run, args.questions / "questions-system.json"), ("oracle", args.oracle_run, args.questions / "questions-oracle.json")]
    errors = 0
    for corpus, run, questions_path in items:
        rows, reports = frozen_rows(run, corpus, json.loads(questions_path.read_text()))
        store = Store({int(r["version_id"]): {"id": int(r["version_id"]), "video_id": k, "payload": r["payload"], "evidence": r["evidence"]} for k, r in reports.items()})
        store.official = {k: int(r["version_id"]) for k, r in reports.items()}
        handler = endpoint(store, model)
        path = out / f"frozen-{corpus}.jsonl"
        done = {json.loads(line)["key"] for line in path.read_text().splitlines()} if path.exists() else set()
        with path.open("a") as sink:
            for row in rows:
                if row["key"] in done:
                    continue
                report = reports[row["incident_id"]]
                view = report_answers.report_view(report["payload"], report["evidence"])
                decision = chat_routing.decide(row["question"], view)
                skipped = corpus == "oracle" and row["class"] == "incident.instrument_holder"
                if decision.route == "report_llm" and (skipped or not model.live):
                    continue
                result = await ask(handler, model, int(report["version_id"]), [{"role": "user", "content": row["question"]}])
                expected = "report_llm" if row["class"] in MODEL_ROUTED_CLASSES else "deterministic"
                message = result.get("message", {})
                record = {
                    **{k: row[k] for k in ("key", "task", "subject", "item_id", "repeat", "corpus", "record_id", "scope", "class", "tier", "incident_id", "question")},
                    "version_id": int(report["version_id"]),
                    "expected_route": expected,
                    "actual_route": decision.route,
                    "route_reason": decision.reason,
                    "llm_invoked": bool(result["calls"]),
                    "outcome": result["outcome"],
                    "answer": {
                        "content": message.get("content", ""),
                        "citations": message.get("citations", []),
                        "insufficient_evidence": bool(message.get("insufficient_evidence")),
                    },
                    "source": message.get("source"),
                    "grounding": result.get("grounding", {}),
                    "raw": result["calls"],
                    "detail": result.get("detail"),
                    "usage": (result["calls"][0]["usage"] if result["calls"] else {"calls": 0}),
                    "elapsed_ms": result.get("elapsed_ms"),
                    "calls": [],
                }
                sink.write(json.dumps(record, sort_keys=True) + "\n")
                sink.flush()
                errors = errors + 1 if result["outcome"] != "answered" else 0
                if errors >= STOP_AFTER_ERRORS:
                    raise Stopped(f"{errors} errors in a row")
                if args.limit and len(model.calls) >= args.limit:
                    raise Stopped(f"limit of {args.limit} calls reached")


async def run_multi_turn(args: argparse.Namespace, model: Metered, out: Path) -> None:
    conversations = json.loads(args.multi_turn.read_text())["conversations"]
    rows = {int(r["id"]): r for r in json.loads(args.revisions.read_text())}
    handler = endpoint(Store(rows), model)
    with (out / "multi-turn.jsonl").open("a") as sink:
        for conversation in conversations:
            history: list[dict[str, str]] = []
            for number, turn in enumerate(conversation["turns"], start=1):
                messages = [*history, {"role": "user", "content": turn["question"]}]
                result = await ask(handler, model, turn["version"], messages)
                content = result.get("message", {}).get("content", "")
                sink.write(json.dumps({"conversation": conversation["id"], "turn": number, **turn, **result}, sort_keys=True) + "\n")
                sink.flush()
                history = [*messages, {"role": "assistant", "content": content}] if content else messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["frozen", "multi-turn"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cap", type=int, required=True, help="tokens this task may use, counting what --out has spent")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many model calls (a smoke test)")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--oracle-run", type=Path)
    parser.add_argument("--system-run", type=Path)
    parser.add_argument("--questions", type=Path, help="the directory with questions-oracle.json and questions-system.json")
    parser.add_argument("--multi-turn", type=Path)
    parser.add_argument("--revisions", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    os.environ.pop(video_check.ENABLED_ENV, None)
    assert not video_check.enabled()
    if args.live:
        load_key(args.env_file)
    inner: Any = grounded_chat.OpenAIChatModel() if args.live else None
    ledger = args.out / f"tokens-{args.task}.txt"
    used = int(ledger.read_text()) if ledger.exists() else 0
    model = Metered(inner, args.cap, used, args.live)
    prompt = grounded_chat.incident_contract.prompt_sha256(grounded_chat.ROUTED_PROMPT_ID)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta = {"task": args.task, "commit": commit, "model": model.model, "prompt_sha256": prompt, "cap": args.cap, "live": args.live, "pace_seconds": PACE_SECONDS, "retries": "rate limits only", "max_rate_waits": MAX_RATE_WAITS, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if args.multi_turn:
        meta["multi_turn_sha256"] = hashlib.sha256(args.multi_turn.read_bytes()).hexdigest()
    with (args.out / "manifest.jsonl").open("a") as sink:
        sink.write(json.dumps(meta) + "\n")
    task = run_frozen(args, model, args.out) if args.task == "frozen" else run_multi_turn(args, model, args.out)
    try:
        asyncio.run(task)
        print("finished")
    except Stopped as stop:
        print(f"stopped: {stop}")
    finally:
        ledger.write_text(str(model.used))
        print(json.dumps({"calls_this_run": len(model.calls), "tokens_total": model.used, "rate_waits": model.rate_waits}))


if __name__ == "__main__":
    main()
