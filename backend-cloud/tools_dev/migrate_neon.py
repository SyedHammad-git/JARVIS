"""Apply the Postgres schema using DATABASE_URL_DIRECT (Neon dev branch only)."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

def load_backend_environment() -> None:
    if os.environ.get("JARVIS_SKIP_DOTENV") == "1":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


load_backend_environment()

# Importing database initializes SQLite; migration DDL itself uses only the direct URL.
os.environ.setdefault("DB_BACKEND", "sqlite")

from app import db as database


def _statements(schema: str):
    return [statement.strip() for statement in schema.split(";") if statement.strip()]


def _schemas():
    owner_migration = "\n".join(
        statement
        for table in database.OWNER_SCOPED_TABLES
        for statement in (
            f"ALTER TABLE IF EXISTS {table} "
            "ADD COLUMN IF NOT EXISTS owner_username TEXT NOT NULL DEFAULT '';",
            f"UPDATE {table} SET owner_username='' WHERE owner_username IS NULL;",
            f"ALTER TABLE IF EXISTS {table} ALTER COLUMN owner_username SET NOT NULL;",
        )
    )
    return (
        database._POSTGRES_SCHEMA,
        database._POSTGRES_SNAPSHOT_SCHEMA,
        getattr(database, "_POSTGRES_VECTOR_SCHEMA", ""),
        owner_migration,
    )


def _table_names(schemas=None):
    names = []
    for schema in schemas or _schemas():
        names.extend(re.findall(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z0-9_]*)", schema, re.I))
    return tuple(dict.fromkeys(name.lower() for name in names))


def _serial_table_names(schema=None):
    source = schema if schema is not None else database._POSTGRES_SCHEMA
    tables = []
    for match in re.finditer(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z0-9_]*)\s*\((.*?)\)",
        source,
        re.IGNORECASE | re.DOTALL,
    ):
        if re.search(r"\bid\s+BIGSERIAL\s+PRIMARY\s+KEY", match.group(2), re.I):
            tables.append(match.group(1).lower())
    return tuple(tables)


def _row_count(cursor, table: str) -> int:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    if not cursor.fetchone()[0]:
        return 0
    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
    return int(cursor.fetchone()[0])


def _print_counts(output, phase: str, counts: dict[str, int]) -> None:
    for table, count in counts.items():
        output(f"{phase} {table}: {count}")


def _reset_sequences(cursor, tables, output=print) -> None:
    for table in tables:
        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f"public.{table}",))
        row = cursor.fetchone()
        if not row or not row[0]:
            continue
        cursor.execute(
            f'SELECT setval(%s::regclass, COALESCE((SELECT MAX(id) FROM "{table}"), 1), '
            f'EXISTS (SELECT 1 FROM "{table}"))',
            (row[0],),
        )
        output(f"Sequence reset {table}: complete")


def migrate_connection(connection, *, dry_run=False, force=False, output=print, schemas=None):
    target_schemas = schemas or _schemas()
    tables = _table_names(target_schemas)
    cursor = connection.cursor()
    try:
        before = {table: _row_count(cursor, table) for table in tables}
        _print_counts(output, "Before", before)
        occupied = {table: count for table, count in before.items() if count}
        if occupied and not force:
            output("Refusing migration: target tables are non-empty; pass --force to continue.")
            _print_counts(output, "After", before)
            return False
        if dry_run:
            output("Dry run: no schema changes applied.")
            _print_counts(output, "After", before)
            return True

        for schema in target_schemas:
            for statement in _statements(schema):
                cursor.execute(statement)
        _reset_sequences(cursor, _serial_table_names(target_schemas[0]), output=output)
        connection.commit()
        after = {table: _row_count(cursor, table) for table in tables}
        _print_counts(output, "After", after)
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main(argv=None, connect_factory=None, output=print) -> int:
    parser = argparse.ArgumentParser(description="Migrate the configured Neon dev branch schema.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts and changes without applying DDL.")
    parser.add_argument("--force", action="store_true", help="Allow migration when target tables contain rows.")
    options = parser.parse_args(argv)

    if not os.environ.get("DATABASE_URL_DIRECT"):
        output("DATABASE_URL_DIRECT is missing; set it to the Neon dev branch for migrations.")
        return 2

    try:
        if connect_factory is None:
            import psycopg2
            connect_factory = psycopg2.connect
        direct_url = database._postgres_url("DATABASE_URL_DIRECT")

        def migrate_once():
            connection = connect_factory(direct_url)
            try:
                return migrate_connection(
                    connection,
                    dry_run=options.dry_run,
                    force=options.force,
                    output=output,
                )
            finally:
                connection.close()

        migrated = database._retry_pg_connection(migrate_once)
        output("Neon schema migration completed." if migrated else "Neon schema migration refused.")
        return 0
    except Exception as exc:
        output(f"Neon schema migration failed ({type(exc).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
