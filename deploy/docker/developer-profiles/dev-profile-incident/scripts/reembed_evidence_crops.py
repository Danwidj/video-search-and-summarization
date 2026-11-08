#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Re-embeds evidence_crops vectors from the text each row stores (its item_name and description, what its card shows).

Why: rows whose evidence entry carried no text were embedded from the passage ": ", so they all share one vector and no
search finds them (decisions.md, 2026-11-09). This script asks the agent's POST /api/v1/incidents/evidence-embeddings,
in its ``evidence`` form, for vectors of the stored text and replaces only the ``embedding`` column of the selected rows.

Selection: ``--row REVISION_ID:ITEM_TYPE:ITEM_ID`` (repeatable), or ``--all-blank`` (every row whose vector is shared
with another row). A selected row with no text to embed is skipped.

Dry run unless ``--apply``: it lists the selected keys and makes no agent call and no write. With ``--apply`` it first
writes a timestamped JSONL backup (key, item_name, description, created_at, old embedding) into ``--backup-dir``, which
must be outside the repository, and stops if the backup cannot be written. Each update is guarded: the row is re-read
just before it is written and is replaced only if it still holds the backed-up vector, and the write itself is filtered
on the row's key and its created_at, so a row rebuilt in the meantime (delete and insert) is never touched.

``--restore BACKUP.jsonl --apply`` puts the backed-up vectors back, only on rows that are still the same rows (same
created_at) and no longer hold the backed-up vector.

Reads INCIDENT_SUPABASE_URL and INCIDENT_SUPABASE_SERVICE_ROLE_KEY from the environment (the profile's .env.local) and
talks to the database over HTTPS (PostgREST); the agent is reached through the start.sh tunnel. Prints keys and counts
only, never a key, a DSN or a vector.

    set -a; . ./.env.local; set +a
    python3 scripts/reembed_evidence_crops.py --row 152:instrument:I1                       # dry run
    python3 scripts/reembed_evidence_crops.py --row 152:instrument:I1 --apply --backup-dir /outside/repo
    python3 scripts/reembed_evidence_crops.py --restore /outside/repo/reembed-evidence-crops-<UTC>.jsonl --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIMENSIONS = 1024
BATCH = 32
ITEM_TYPES = ("entity", "instrument", "asset")
COLUMNS = "revision_id,item_type,item_id,item_name,description,created_at,embedding"

Key = tuple[int, str, str]


@dataclass(frozen=True)
class Row:
    """One evidence_crops row as the script reads it; embedding is the vector's text form, as PostgREST returns it."""

    revision_id: int
    item_type: str
    item_id: str
    item_name: str
    description: str
    created_at: str
    embedding: str | None

    @property
    def key(self) -> Key:
        return (self.revision_id, self.item_type, self.item_id)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Row:
        return cls(
            revision_id=int(data["revision_id"]),
            item_type=str(data["item_type"]),
            item_id=str(data["item_id"]),
            item_name=str(data.get("item_name") or ""),
            description=str(data.get("description") or ""),
            created_at=str(data["created_at"]),
            embedding=data.get("embedding"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "item_type": self.item_type,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "description": self.description,
            "created_at": self.created_at,
            "embedding": self.embedding,
        }


def key_text(key: Key) -> str:
    return f"{key[0]}:{key[1]}:{key[2]}"


def parse_key(text: str) -> Key:
    """``152:instrument:I1`` -> (152, "instrument", "I1")."""
    parts = text.split(":")
    if (
        len(parts) != 3
        or not parts[0].isdigit()
        or parts[1] not in ITEM_TYPES
        or not parts[2].strip()
    ):
        raise argparse.ArgumentTypeError(
            f"expected REVISION_ID:ITEM_TYPE:ITEM_ID with a type in {ITEM_TYPES}: {text!r}"
        )
    return (int(parts[0]), parts[1], parts[2].strip())


def parse_vector(text: str | None) -> list[float] | None:
    if text is None:
        return None
    values = json.loads(text) if isinstance(text, str) else text
    return [float(x) for x in values]


def same_vector(a: str | None, b: str | None, tolerance: float = 1e-6) -> bool:
    """Whether two stored vectors are the same (both absent counts as the same)."""
    va, vb = parse_vector(a), parse_vector(b)
    if va is None or vb is None:
        return va is None and vb is None
    return len(va) == len(vb) and all(
        abs(x - y) <= tolerance for x, y in zip(va, vb, strict=True)
    )


def vector_signature(text: str | None) -> tuple[float, ...] | None:
    """A vector rounded to 6 decimals, so copies of one vector group together whatever their text formatting."""
    values = parse_vector(text)
    return None if values is None else tuple(round(x, 6) for x in values)


def blank_keys(rows: Iterable[Row]) -> list[Key]:
    """Rows whose vector is shared with at least one other row: the vector of a passage with no text in it."""
    rows = list(rows)
    counts = Counter(
        vector_signature(row.embedding) for row in rows if row.embedding is not None
    )
    return sorted(
        row.key
        for row in rows
        if row.embedding is not None and counts[vector_signature(row.embedding)] > 1
    )


def has_text(row: Row) -> bool:
    """The console's rule (evidenceSearchTexts): a description, or a name other than the bare item type."""
    name = row.item_name.strip()
    return bool(row.description.strip()) or bool(name and name != row.item_type)


def select(
    rows: Iterable[Row], wanted: list[Key] | None, all_blank: bool
) -> tuple[list[Row], list[str]]:
    """The rows to re-embed, and the problems that stop the run (an unknown key)."""
    by_key = {row.key: row for row in rows}
    keys = (
        blank_keys(by_key.values()) if all_blank else list(dict.fromkeys(wanted or []))
    )
    problems = [
        f"no evidence_crops row {key_text(key)}" for key in keys if key not in by_key
    ]
    return [by_key[key] for key in keys if key in by_key], problems


def evidence_body(rows: Iterable[Row]) -> dict[str, list[dict[str, str]]]:
    """The agent's ``evidence`` request body: the stored text of each row, exactly what its card shows."""
    return {
        "evidence": [
            {
                "item_type": r.item_type,
                "item_id": r.item_id,
                "item_name": r.item_name,
                "description": r.description,
            }
            for r in rows
        ]
    }


def vectors_from_response(rows: list[Row], payload: Any) -> dict[Key, list[float]]:
    """Checks the agent's answer: one 1024-number vector per row sent, matched by type and ID."""
    if not isinstance(payload, list):
        raise TypeError("the agent returned no embedding list")
    wanted = {(r.item_type, r.item_id): r.key for r in rows}
    out: dict[Key, list[float]] = {}
    for item in payload:
        pair = (
            (item.get("item_type"), item.get("item_id"))
            if isinstance(item, dict)
            else None
        )
        if pair not in wanted:
            raise ValueError(
                f"the agent returned a vector for an item that was not sent: {pair}"
            )
        vector = item.get("embedding")
        if not isinstance(vector, list) or len(vector) != DIMENSIONS:
            raise ValueError(
                f"the agent returned a malformed vector for {pair} (expected {DIMENSIONS} numbers)"
            )
        out[wanted[pair]] = [float(x) for x in vector]
    if len(out) != len(rows):
        raise ValueError(f"the agent returned {len(out)} vectors for {len(rows)} items")
    return out


def vector_text(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def backup_path(directory: Path, now: datetime | None = None) -> Path:
    # timezone.utc, not datetime.UTC: the script runs on the laptop's system Python, which may be 3.10.
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
    return directory / f"reembed-evidence-crops-{stamp}.jsonl"


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def write_backup(path: Path, rows: Iterable[Row]) -> int:
    """Writes the rows to a new JSONL file (never overwrites one); returns the count. Raises when it cannot."""
    rows = list(rows)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json()) + "\n")
    return len(rows)


def read_backup(path: Path) -> list[Row]:
    with path.open(encoding="utf-8") as handle:
        return [Row.from_json(json.loads(line)) for line in handle if line.strip()]


class Database:
    """evidence_crops over PostgREST with the service key. Only the embedding column is ever written."""

    def __init__(
        self, url: str, key: str, opener: Callable[..., Any] = urllib.request.urlopen
    ) -> None:
        self._base = url.rstrip("/") + "/rest/v1/evidence_crops"
        self._headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        self._open = opener

    def _request(self, method: str, query: dict[str, str], body: Any = None) -> Any:
        url = f"{self._base}?{urllib.parse.urlencode(query)}"
        headers = dict(self._headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = "return=representation"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with self._open(request, timeout=60) as response:
            return json.load(response)

    def rows(self) -> list[Row]:
        out: list[Row] = []
        offset = 0
        while True:
            page = self._request(
                "GET",
                {
                    "select": COLUMNS,
                    "order": "revision_id,item_type,item_id",
                    "limit": "1000",
                    "offset": str(offset),
                },
            )
            out.extend(Row.from_json(item) for item in page)
            if len(page) < 1000:
                return out
            offset += 1000

    @staticmethod
    def _key_filter(key: Key) -> dict[str, str]:
        return {
            "revision_id": f"eq.{key[0]}",
            "item_type": f"eq.{key[1]}",
            "item_id": f"eq.{key[2]}",
        }

    def row(self, key: Key) -> Row | None:
        found = self._request("GET", {"select": COLUMNS, **self._key_filter(key)})
        return Row.from_json(found[0]) if found else None

    def set_embedding(self, key: Key, created_at: str, vector: str) -> int:
        """Replaces the embedding of the row with this key and created_at; returns how many rows changed."""
        query = {
            **self._key_filter(key),
            "created_at": f"eq.{created_at}",
            "select": "revision_id",
        }
        return len(self._request("PATCH", query, {"embedding": vector}))


class Agent:
    """The agent's POST /api/v1/incidents/evidence-embeddings, reached through the start.sh tunnel."""

    def __init__(
        self, url: str, opener: Callable[..., Any] = urllib.request.urlopen
    ) -> None:
        self._url = url.rstrip("/") + "/api/v1/incidents/evidence-embeddings"
        self._open = opener

    def embed(self, rows: list[Row]) -> dict[Key, list[float]]:
        out: dict[Key, list[float]] = {}
        for start in range(0, len(rows), BATCH):
            batch = rows[start : start + BATCH]
            request = urllib.request.Request(
                self._url,
                json.dumps(evidence_body(batch)).encode(),
                {"Content-Type": "application/json"},
            )
            with self._open(request, timeout=120) as response:
                out.update(vectors_from_response(batch, json.load(response)))
        return out


def guarded_replace(
    db: Database, backed_up: Row, new_vector: str, expect_current: str | None
) -> str:
    """Writes new_vector over one row only when it is still the backed-up row holding expect_current; returns the outcome."""
    current = db.row(backed_up.key)
    if current is None:
        return "gone"
    if current.created_at != backed_up.created_at:
        return "rebuilt"
    if not same_vector(current.embedding, expect_current):
        return "changed"
    changed = db.set_embedding(backed_up.key, backed_up.created_at, new_vector)
    if changed != 1:
        return "changed"
    after = db.row(backed_up.key)
    return (
        "replaced"
        if after is not None and same_vector(after.embedding, new_vector)
        else "unverified"
    )


def reembed(
    db: Database,
    agent: Agent,
    rows: list[Row],
    backup_dir: Path,
    log: Callable[[str], None],
) -> Counter[str]:
    path = backup_path(backup_dir)
    written = write_backup(path, rows)
    log(f"backup of {written} rows written to {path}")
    vectors = agent.embed(rows)
    log(f"the agent returned {len(vectors)} vectors")
    outcomes: Counter[str] = Counter()
    for row in rows:
        outcome = guarded_replace(db, row, vector_text(vectors[row.key]), row.embedding)
        outcomes[outcome] += 1
        log(f"{key_text(row.key)}: {outcome}")
    return outcomes


def restore(db: Database, rows: list[Row], log: Callable[[str], None]) -> Counter[str]:
    """Puts each backed-up vector back on the same row (same created_at), if the row no longer holds it."""
    outcomes: Counter[str] = Counter()
    for row in rows:
        current = db.row(row.key)
        if current is None or current.created_at != row.created_at:
            outcome = "gone" if current is None else "rebuilt"
        elif same_vector(current.embedding, row.embedding):
            outcome = "already"
        elif row.embedding is None:
            outcome = "no-backup-vector"
        else:
            outcome = guarded_replace(db, row, row.embedding, current.embedding)
            outcome = "restored" if outcome == "replaced" else outcome
        outcomes[outcome] += 1
        log(f"{key_text(row.key)}: {outcome}")
    return outcomes


def repo_root(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument(
        "--row",
        type=parse_key,
        action="append",
        help="REVISION_ID:ITEM_TYPE:ITEM_ID (repeatable)",
    )
    what.add_argument(
        "--all-blank",
        action="store_true",
        help="every row whose vector is shared with another row",
    )
    what.add_argument(
        "--restore",
        type=Path,
        help="a backup JSONL this script wrote: put its vectors back",
    )
    parser.add_argument(
        "--agent",
        default="http://localhost:8000",
        help="the vss-agent (default: the start.sh tunnel)",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="directory for the backup file, outside the repository",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write; without it nothing is written or sent",
    )
    args = parser.parse_args(argv)

    url = os.environ.get("INCIDENT_SUPABASE_URL", "").strip()
    key = os.environ.get("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        print(
            "INCIDENT_SUPABASE_URL and INCIDENT_SUPABASE_SERVICE_ROLE_KEY must be set",
            file=sys.stderr,
        )
        return 2
    db = Database(url, key)

    if args.restore:
        rows = read_backup(args.restore)
        print(f"{len(rows)} rows in the backup")
        if not args.apply:
            for row in rows:
                print(f"would restore {key_text(row.key)}")
            print("dry run: nothing written (add --apply)")
            return 0
        outcomes = restore(db, rows, print)
        print("restore:", dict(outcomes))
        return 0 if set(outcomes) <= {"restored", "already"} else 1

    chosen, problems = select(db.rows(), args.row, args.all_blank)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 2
    skipped = [row for row in chosen if not has_text(row)]
    chosen = [row for row in chosen if has_text(row)]
    for row in skipped:
        print(f"skip {key_text(row.key)}: no stored text to embed")
    print(f"{len(chosen)} rows selected")
    for row in chosen:
        print(f"  {key_text(row.key)}")
    if not args.apply:
        print("dry run: no agent call and nothing written (add --apply)")
        return 0
    if not chosen:
        return 0
    if args.backup_dir is None:
        print("--apply needs --backup-dir (outside the repository)", file=sys.stderr)
        return 2
    root = repo_root(Path(__file__).resolve().parent)
    if root is not None and inside(args.backup_dir, root):
        print("--backup-dir must be outside the repository", file=sys.stderr)
        return 2
    if not args.backup_dir.is_dir():
        print(f"--backup-dir is not a directory: {args.backup_dir}", file=sys.stderr)
        return 2
    outcomes = reembed(db, Agent(args.agent), chosen, args.backup_dir, print)
    print("re-embed:", dict(outcomes))
    return 0 if set(outcomes) <= {"replaced"} else 1


if __name__ == "__main__":
    sys.exit(main())
