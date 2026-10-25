"""Apply the Postgres schema using DATABASE_URL_DIRECT (Neon dev branch only)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

# Importing database initializes SQLite; migration DDL itself uses only the direct URL.
os.environ["DB_BACKEND"] = "sqlite"
sys.path.insert(0, str(ROOT))

import database


def _statements(schema: str):
    return [statement.strip() for statement in schema.split(";") if statement.strip()]


def main() -> int:
    if not os.environ.get("DATABASE_URL_DIRECT"):
        print("DATABASE_URL_DIRECT is missing; set it to the Neon dev branch for migrations.")
        return 2

    try:
        import psycopg2
        direct_url = database._postgres_url("DATABASE_URL_DIRECT")

        def migrate_once():
            with psycopg2.connect(direct_url) as connection:
                with connection.cursor() as cursor:
                    for statement in _statements(database._POSTGRES_SCHEMA):
                        cursor.execute(statement)
                    for statement in _statements(database._POSTGRES_SNAPSHOT_SCHEMA):
                        cursor.execute(statement)

        database._retry_pg_connection(migrate_once)
        print("Neon schema migration completed.")
        return 0
    except Exception as exc:
        print(f"Neon schema migration failed ({type(exc).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
