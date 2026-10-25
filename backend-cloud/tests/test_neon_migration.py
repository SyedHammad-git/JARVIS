"""Mocked safety checks for Neon migration operations; never opens a real DB."""
from urllib.parse import parse_qs, urlsplit

import pytest

import app.db as database
import tools_dev.migrate_neon as migration


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.closed = False
        self.result = None

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if "pg_get_serial_sequence" in statement:
            self.result = ("public.devices_id_seq",)
        else:
            self.result = None

    def fetchone(self):
        return self.result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def patch_migration(monkeypatch, counts):
    monkeypatch.setattr(migration, "_schemas", lambda: ("CREATE TABLE IF NOT EXISTS devices (id BIGSERIAL PRIMARY KEY);",))
    monkeypatch.setattr(migration, "_table_names", lambda schemas: ("devices",))
    monkeypatch.setattr(migration, "_serial_table_names", lambda schema: ("devices",))
    monkeypatch.setattr(migration, "_row_count", lambda cursor, table: counts[table])
    resets = []
    monkeypatch.setattr(migration, "_reset_sequences", lambda cursor, tables, output: resets.append(tuple(tables)))
    return resets


def test_dry_run_reports_before_after_and_never_executes_ddl(monkeypatch):
    connection = FakeConnection()
    patch_migration(monkeypatch, {"devices": 0})
    output = []

    assert migration.migrate_connection(connection, dry_run=True, output=output.append)

    assert connection.fake_cursor.executed == []
    assert connection.commits == 0
    assert output == [
        "Before devices: 0",
        "Dry run: no schema changes applied.",
        "After devices: 0",
    ]


def test_nonempty_targets_refuse_without_force(monkeypatch):
    connection = FakeConnection()
    patch_migration(monkeypatch, {"devices": 4})
    output = []

    assert not migration.migrate_connection(connection, output=output.append)

    assert connection.fake_cursor.executed == []
    assert "Refusing migration" in output[1]
    assert output[-1] == "After devices: 4"


def test_force_applies_schema_resets_sequences_and_reports_counts(monkeypatch):
    connection = FakeConnection()
    counts = iter((3, 3))
    monkeypatch.setattr(migration, "_schemas", lambda: ("CREATE TABLE IF NOT EXISTS devices (id BIGSERIAL PRIMARY KEY);",))
    monkeypatch.setattr(migration, "_table_names", lambda schemas: ("devices",))
    monkeypatch.setattr(migration, "_serial_table_names", lambda schema: ("devices",))
    monkeypatch.setattr(migration, "_row_count", lambda cursor, table: next(counts))
    resets = []
    monkeypatch.setattr(migration, "_reset_sequences", lambda cursor, tables, output: resets.append(tuple(tables)))
    output = []

    assert migration.migrate_connection(connection, force=True, output=output.append)

    assert connection.fake_cursor.executed == [("CREATE TABLE IF NOT EXISTS devices (id BIGSERIAL PRIMARY KEY)", None)]
    assert connection.commits == 1
    assert resets == [("devices",)]
    assert output == ["Before devices: 3", "After devices: 3"]


def test_sequence_reset_uses_current_maximum_id():
    cursor = FakeCursor()
    output = []

    migration._reset_sequences(cursor, ("devices",), output=output.append)

    assert "pg_get_serial_sequence" in cursor.executed[0][0]
    assert "setval" in cursor.executed[1][0]
    assert "MAX(id)" in cursor.executed[1][0]
    assert cursor.executed[1][1] == ("public.devices_id_seq",)
    assert output == ["Sequence reset devices: complete"]


def test_migration_cli_connects_only_to_direct_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://pooled@ep-dev-pooler.neon.tech/app")
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://direct@ep-dev.neon.tech/app")
    connection = FakeConnection()
    patch_migration(monkeypatch, {"devices": 0})
    connect_urls = []
    output = []

    status = migration.main(
        ["--dry-run"],
        connect_factory=lambda url: connect_urls.append(url) or connection,
        output=output.append,
    )

    assert status == 0
    assert len(connect_urls) == 1
    assert urlsplit(connect_urls[0]).hostname == "ep-dev.neon.tech"
    assert parse_qs(urlsplit(connect_urls[0]).query)["sslmode"] == ["require"]
    assert connection.closed
