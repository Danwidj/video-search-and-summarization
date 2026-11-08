# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests of scripts/reembed_evidence_crops.py: selection, the guarded update and restore, with no network.

python3 -m unittest discover -s scripts/tests
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reembed_evidence_crops as rc

BLANK = "[" + ",".join(["0.03125"] * 1024) + "]"
OTHER = "[" + ",".join(["0.5"] + ["0"] * 1023) + "]"
NEW = [0.25] + [0.0] * 1023


def row(
    rev: int,
    kind: str,
    item: str,
    name: str = "",
    desc: str = "",
    vec: str | None = BLANK,
    at: str = "t0",
) -> rc.Row:
    return rc.Row(rev, kind, item, name, desc, at, vec)


class FakeDb:
    """The two calls the guard uses: read one row, and write the embedding of a row with a given key and created_at."""

    def __init__(self, rows: list[rc.Row]) -> None:
        self.rows = {r.key: r for r in rows}
        self.writes: list[tuple[rc.Key, str]] = []

    def row(self, key: rc.Key) -> rc.Row | None:
        return self.rows.get(key)

    def set_embedding(self, key: rc.Key, created_at: str, vector: str) -> int:
        current = self.rows.get(key)
        if current is None or current.created_at != created_at:
            return 0
        self.writes.append((key, created_at))
        self.rows[key] = rc.Row(**{**current.to_json(), "embedding": vector})
        return 1


class FakeAgent:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def embed(self, rows: list[rc.Row]) -> dict[rc.Key, list[float]]:
        self.sent.append(rc.evidence_body(rows))
        return {r.key: NEW for r in rows}


class SelectionTests(unittest.TestCase):
    def test_parse_key(self) -> None:
        self.assertEqual(rc.parse_key("152:instrument:I1"), (152, "instrument", "I1"))
        for bad in ("152:tool:I1", "x:entity:E1", "152:entity", "152:entity:"):
            with self.assertRaises(argparse.ArgumentTypeError):
                rc.parse_key(bad)

    def test_all_blank_picks_only_rows_sharing_a_vector(self) -> None:
        rows = [
            row(152, "instrument", "I1", "spray bottle", "A white bottle."),
            row(200, "instrument", "I1", "knife", "knife"),
            row(152, "entity", "E1", "man", "A man.", vec=OTHER),
        ]
        self.assertEqual(
            rc.blank_keys(rows), [(152, "instrument", "I1"), (200, "instrument", "I1")]
        )

    def test_explicit_rows_and_unknown_keys(self) -> None:
        rows = [row(152, "instrument", "I1", "spray bottle", "A white bottle.")]
        chosen, problems = rc.select(
            rows, [(152, "instrument", "I1"), (9, "entity", "E1")], all_blank=False
        )
        self.assertEqual([r.key for r in chosen], [(152, "instrument", "I1")])
        self.assertEqual(problems, ["no evidence_crops row 9:entity:E1"])

    def test_has_text_matches_the_console_rule(self) -> None:
        self.assertTrue(rc.has_text(row(1, "instrument", "I1", "spray bottle", "")))
        self.assertTrue(rc.has_text(row(1, "entity", "E1", "entity", "A man.")))
        self.assertFalse(rc.has_text(row(1, "entity", "E1", "entity", "  ")))
        self.assertFalse(rc.has_text(row(1, "entity", "E1", "", "")))

    def test_the_agent_gets_the_stored_text(self) -> None:
        body = rc.evidence_body(
            [row(152, "instrument", "I1", "spray bottle", "A white bottle.")]
        )
        self.assertEqual(
            body,
            {
                "evidence": [
                    {
                        "item_type": "instrument",
                        "item_id": "I1",
                        "item_name": "spray bottle",
                        "description": "A white bottle.",
                    }
                ]
            },
        )

    def test_agent_answer_is_checked(self) -> None:
        rows = [row(152, "instrument", "I1", "spray bottle", "x")]
        good = [{"item_type": "instrument", "item_id": "I1", "embedding": NEW}]
        self.assertEqual(
            rc.vectors_from_response(rows, good), {(152, "instrument", "I1"): NEW}
        )
        for bad in (
            {},
            [],
            [{"item_type": "entity", "item_id": "E1", "embedding": NEW}],
            [{"item_type": "instrument", "item_id": "I1", "embedding": [0.1] * 10}],
        ):
            with self.assertRaises((ValueError, TypeError)):
                rc.vectors_from_response(rows, bad)


class GuardTests(unittest.TestCase):
    def test_replaces_only_a_row_still_holding_the_backed_up_vector(self) -> None:
        target = row(152, "instrument", "I1", "spray bottle", "x")
        db = FakeDb([target])
        self.assertEqual(
            rc.guarded_replace(db, target, rc.vector_text(NEW), BLANK), "replaced"
        )
        self.assertTrue(
            rc.same_vector(db.rows[target.key].embedding, rc.vector_text(NEW))
        )

    def test_a_row_changed_since_the_backup_is_left_alone(self) -> None:
        target = row(152, "instrument", "I1", "spray bottle", "x")
        db = FakeDb([row(152, "instrument", "I1", "spray bottle", "x", vec=OTHER)])
        self.assertEqual(
            rc.guarded_replace(db, target, rc.vector_text(NEW), BLANK), "changed"
        )
        self.assertEqual(db.writes, [])

    def test_a_rebuilt_or_deleted_row_is_left_alone(self) -> None:
        target = row(152, "instrument", "I1", "spray bottle", "x", at="t0")
        db = FakeDb([row(152, "instrument", "I1", "spray bottle", "x", at="t1")])
        self.assertEqual(
            rc.guarded_replace(db, target, rc.vector_text(NEW), BLANK), "rebuilt"
        )
        self.assertEqual(
            rc.guarded_replace(FakeDb([]), target, rc.vector_text(NEW), BLANK), "gone"
        )
        self.assertEqual(db.writes, [])

    def test_reembed_backs_up_first_and_touches_only_the_selected_row(self) -> None:
        target = row(152, "instrument", "I1", "spray bottle", "x")
        other = row(200, "instrument", "I1", "knife", "knife")
        db, agent = FakeDb([target, other]), FakeAgent()
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = rc.reembed(db, agent, [target], Path(tmp), lambda _line: None)
            backups = list(Path(tmp).glob("reembed-evidence-crops-*.jsonl"))
            self.assertEqual(len(backups), 1)
            saved = rc.read_backup(backups[0])
        self.assertEqual(outcomes, Counter({"replaced": 1}))
        self.assertEqual([r.key for r in saved], [target.key])
        self.assertEqual(saved[0].embedding, BLANK, "the backup holds the old vector")
        self.assertEqual(db.writes, [(target.key, "t0")])
        self.assertEqual(db.rows[other.key].embedding, BLANK)
        self.assertEqual(agent.sent[0]["evidence"][0]["item_name"], "spray bottle")

    def test_no_backup_no_write(self) -> None:
        target = row(152, "instrument", "I1", "spray bottle", "x")
        db, agent = FakeDb([target]), FakeAgent()
        with self.assertRaises(OSError):
            rc.reembed(
                db, agent, [target], Path("/nonexistent/dir"), lambda _line: None
            )
        self.assertEqual(agent.sent, [])
        self.assertEqual(db.writes, [])

    def test_a_backup_file_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.jsonl"
            rc.write_backup(path, [row(1, "entity", "E1")])
            with self.assertRaises(FileExistsError):
                rc.write_backup(path, [row(2, "entity", "E1")])


class RestoreTests(unittest.TestCase):
    def test_restore_puts_the_old_vector_back_on_the_same_row(self) -> None:
        backed = row(152, "instrument", "I1", "spray bottle", "x", vec=BLANK)
        db = FakeDb(
            [row(152, "instrument", "I1", "spray bottle", "x", vec=rc.vector_text(NEW))]
        )
        self.assertEqual(
            rc.restore(db, [backed], lambda _line: None), Counter({"restored": 1})
        )
        self.assertTrue(rc.same_vector(db.rows[backed.key].embedding, BLANK))

    def test_restore_skips_rebuilt_rows_and_rows_already_restored(self) -> None:
        backed = row(152, "instrument", "I1", "spray bottle", "x", vec=BLANK, at="t0")
        rebuilt = FakeDb(
            [row(152, "instrument", "I1", "spray bottle", "x", vec=OTHER, at="t1")]
        )
        self.assertEqual(
            rc.restore(rebuilt, [backed], lambda _line: None), Counter({"rebuilt": 1})
        )
        same = FakeDb([backed])
        self.assertEqual(
            rc.restore(same, [backed], lambda _line: None), Counter({"already": 1})
        )
        self.assertEqual(rebuilt.writes + same.writes, [])


class SafetyTests(unittest.TestCase):
    def test_backup_dir_inside_the_repository_is_detected(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(rc.inside(root / "x", root))
        self.assertFalse(rc.inside(Path("/tmp"), root))

    def test_dry_run_prints_keys_only_and_writes_nothing(self) -> None:
        rows = [row(152, "instrument", "I1", "spray bottle", "A white bottle.")]

        class ReadOnlyDb:
            def __init__(self, *_args: object) -> None:
                pass

            def rows(self) -> list[rc.Row]:
                return rows

        out = io.StringIO()
        original, rc.Database = rc.Database, ReadOnlyDb  # type: ignore[misc]
        environ = {
            "INCIDENT_SUPABASE_URL": "https://db.example",
            "INCIDENT_SUPABASE_SERVICE_ROLE_KEY": "secret-key",
        }
        saved_env = {k: rc.os.environ.get(k) for k in environ}
        rc.os.environ.update(environ)
        saved_stdout, sys.stdout = sys.stdout, out
        try:
            self.assertEqual(rc.main(["--row", "152:instrument:I1"]), 0)
        finally:
            sys.stdout = saved_stdout
            rc.Database = original  # type: ignore[misc]
            for k, v in saved_env.items():
                if v is None:
                    rc.os.environ.pop(k, None)
                else:
                    rc.os.environ[k] = v
        text = out.getvalue()
        self.assertIn("152:instrument:I1", text)
        self.assertIn("dry run", text)
        self.assertNotIn("secret-key", text)
        self.assertNotIn("0.03125", text, "no vector is printed")
        self.assertNotIn(json.dumps(BLANK), text)


class FakeAgentHttp:
    """Answers like the agent: one vector per distinct (item_type, item_id) in the request, recording each request body."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001
        body = json.loads(request.data.decode())
        self.bodies.append(body)
        seen: dict[tuple[str, str], dict] = {}
        for item in body["evidence"]:
            pair = (item["item_type"], item["item_id"])
            seen.setdefault(
                pair, {"item_type": pair[0], "item_id": pair[1], "embedding": NEW}
            )
        return io.BytesIO(json.dumps(list(seen.values())).encode())


class AgentBatchTests(unittest.TestCase):
    def test_rows_from_different_revisions_sharing_items_all_get_vectors(self) -> None:
        # The 2026-11-09 failure: 32 rows of one batch covered only 2 distinct (item_type, item_id) pairs.
        rows = [
            row(152 + i, "entity", "E1", "man", f"A man in scene {i}.")
            if i % 2 == 0
            else row(152 + i, "asset", "A1", "bottle", f"A bottle in scene {i}.")
            for i in range(32)
        ]
        http = FakeAgentHttp()
        vectors = rc.Agent("http://127.0.0.1:8000", opener=http).embed(rows)
        self.assertEqual(set(vectors), {r.key for r in rows})
        for body in http.bodies:
            pairs = [(i["item_type"], i["item_id"]) for i in body["evidence"]]
            self.assertEqual(
                len(pairs), len(set(pairs)), "a request never repeats an item pair"
            )

    def test_a_request_missing_items_is_refused(self) -> None:
        rows = [row(1, "entity", "E1", "man", "a"), row(2, "entity", "E1", "man", "b")]

        def short_answer(request, timeout=None):  # noqa: ANN001
            return io.BytesIO(
                json.dumps(
                    [{"item_type": "entity", "item_id": "E1", "embedding": NEW}]
                ).encode()
            )

        with self.assertRaises(ValueError):
            rc.vectors_from_response(rows, json.loads(short_answer(None).read()))


if __name__ == "__main__":
    unittest.main()
