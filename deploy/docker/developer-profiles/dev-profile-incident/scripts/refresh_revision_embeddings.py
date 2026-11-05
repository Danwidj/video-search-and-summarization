#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Re-embeds the summary vector of every searchable version, after the summary text recipe changed.

The text is built by the agent (``revision_summary_text``: "type: title" then the description), so this script sends the
type, title and description to the agent's POST /api/v1/incidents/revision-embedding and stores the vector it returns:
refresh_revision_embedding replaces a stored vector, set_revision_embedding fills a missing one. One version per video is
searchable (official, else newest). Nothing else in report_revisions changes.

Dry run unless --apply. With --apply it first writes --backup (every searchable revision id with its old vector) and
refuses to go on if that fails. Reads INCIDENT_DB_DSN from the environment (the profile's .env.local); --db-tunnel
HOST:PORT replaces the DSN's host and port when the laptop reaches the pooler through an ssh tunnel (never printed).

    set -a; . ./.env.local; set +a
    uv run --no-project --with 'psycopg[binary]' python scripts/refresh_revision_embeddings.py \
        --agent http://127.0.0.1:18001 --db-tunnel 127.0.0.1:15432 --backup /path/backup.json [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request

import psycopg

ROWS = """
SELECT v.id, r.id, r.payload #>> '{incident,type}', r.payload #>> '{incident,title}', r.payload #>> '{incident,description}',
       r.embedding::text
FROM public.videos AS v
JOIN public.report_revisions AS r ON r.id = public.searchable_revision_id(v.id)
ORDER BY v.id
"""


def tunnelled(dsn: str, hostport: str | None) -> str:
    if not hostport:
        return dsn
    parts = urllib.parse.urlsplit(dsn)
    userinfo = parts.netloc.rpartition("@")[0]
    return urllib.parse.urlunsplit(parts._replace(netloc=f"{userinfo}@{hostport}"))


def embed(agent: str, incident_type: str | None, title: str | None, description: str | None) -> list[float]:
    body = json.dumps({"incident_type": incident_type, "title": title, "description": description}).encode()
    request = urllib.request.Request(
        f"{agent.rstrip('/')}/api/v1/incidents/revision-embedding", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        vector = json.load(response)["embedding"]
    if len(vector) != 1024:
        raise SystemExit(f"the agent returned {len(vector)} numbers, expected 1024")
    return vector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", required=True, help="a vss-agent whose revision-embedding route knows incident_type")
    parser.add_argument("--db-tunnel", help="HOST:PORT to use instead of the DSN's host and port")
    parser.add_argument("--backup", help="file for the revision ids and old vectors (required with --apply)")
    parser.add_argument("--apply", action="store_true", help="store the new vectors; without it only list")
    args = parser.parse_args()
    if args.apply and not args.backup:
        raise SystemExit("--apply needs --backup")

    with psycopg.connect(tunnelled(os.environ["INCIDENT_DB_DSN"], args.db_tunnel)) as conn:
        rows = conn.execute(ROWS).fetchall()
        if args.backup:
            with open(args.backup, "w") as handle:
                json.dump(
                    [{"video_id": v, "revision_id": r, "old_embedding": old} for v, r, _t, _ti, _d, old in rows], handle
                )
            print(f"backup of {len(rows)} searchable versions written to {args.backup}")
        stored = 0
        for video_id, revision_id, incident_type, title, description, old in rows:
            if not (title or "").strip() and not (description or "").strip():
                print(f"skip {video_id} revision {revision_id}: no title or description")
                continue
            action = "refresh" if old is not None else "set"
            if not args.apply:
                print(f"would {action} {video_id} revision {revision_id} (type {incident_type})")
                continue
            vector = embed(args.agent, incident_type, title, description)
            literal = "[" + ",".join(repr(float(n)) for n in vector) + "]"
            function = "refresh_revision_embedding" if old is not None else "set_revision_embedding"
            done = conn.execute(
                f"SELECT public.{function}(%s, %s, %s::extensions.vector)", (video_id, revision_id, literal)
            ).fetchone()[0]
            conn.commit()
            stored += 1 if done else 0
            print(f"{action} {video_id} revision {revision_id} (type {incident_type}): {'written' if done else 'NOT written'}")
        print(f"{len(rows)} searchable versions; {stored} vectors written")


if __name__ == "__main__":
    main()
