"""Backfill memory_facts into Neon pgvector using Gemini embeddings."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
except ImportError:
    pass

def _load_database():
    import database
    return database


def _add_memory(memory_id, fact, metadata):
    from vector.pg_store import add_memory
    return add_memory(memory_id, fact, metadata)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backfill memory facts into Neon pgvector.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to process; 0 means all.")
    args = parser.parse_args(argv)
    direct_url = os.environ.get("DATABASE_URL_DIRECT", "").strip()
    if not direct_url:
        print("Backfill requires DATABASE_URL_DIRECT for the Neon dev branch.")
        return 2
    os.environ["DATABASE_URL"] = direct_url
    database = _load_database()
    if database.DB_BACKEND != "postgres":
        print("Backfill requires DB_BACKEND=postgres on the Neon dev branch.")
        return 2

    sql = "SELECT id,fact,category,source FROM memory_facts ORDER BY id"
    params = ()
    if args.limit > 0:
        sql += " LIMIT ?"
        params = (args.limit,)
    facts = database.db_read(sql, params)
    added = 0
    skipped = 0
    for row in facts:
        metadata = {"category": row.get("category", "general"), "source": row.get("source", "learned")}
        if _add_memory(str(row["id"]), row["fact"], metadata):
            added += 1
        else:
            skipped += 1
    print(f"Backfill complete: indexed={added}, skipped={skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
