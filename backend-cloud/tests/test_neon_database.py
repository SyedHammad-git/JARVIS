"""Neon connection and migration behavior, without connecting to a database."""
import re
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import app.db as database
import pytest


def test_pooled_url_always_requires_ssl_without_exposing_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:private-value@ep-example-pooler.neon.tech/app?sslmode=disable&application_name=jarvis",
    )

    pooled_url = database._postgres_url("DATABASE_URL")
    parsed = urlsplit(pooled_url)

    assert parsed.hostname == "ep-example-pooler.neon.tech"
    assert parse_qs(parsed.query) == {"sslmode": ["require"], "application_name": ["jarvis"]}


def test_direct_migration_url_uses_direct_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://pooled@ep-example-pooler.neon.tech/app")
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://direct@ep-example.neon.tech/app")

    direct_url = database._postgres_url("DATABASE_URL_DIRECT")

    assert urlsplit(direct_url).hostname == "ep-example.neon.tech"
    assert "pooler" not in urlsplit(direct_url).hostname
    assert parse_qs(urlsplit(direct_url).query)["sslmode"] == ["require"]


def test_database_url_roles_cannot_be_reversed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@ep-example.neon.tech/app")
    with pytest.raises(ValueError, match="pooled endpoint"):
        database._postgres_url("DATABASE_URL")

    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://user@ep-example-pooler.neon.tech/app")
    with pytest.raises(ValueError, match="direct endpoint"):
        database._postgres_url("DATABASE_URL_DIRECT")


def test_converted_schema_contains_devices_once_and_postgres_types():
    schema = database.postgres_schema_from_sqlite()

    assert schema.count("CREATE TABLE IF NOT EXISTS devices") == 1
    assert "BIGSERIAL PRIMARY KEY" in schema
    assert re.search(r'"trigger"\s+TEXT', schema)
    assert "CREATE TABLE IF NOT EXISTS devices" not in database._POSTGRES_SNAPSHOT_SCHEMA
    assert "image BYTEA NOT NULL" in database._POSTGRES_SNAPSHOT_SCHEMA
    assert "expires_at TIMESTAMPTZ NOT NULL" in database._POSTGRES_SNAPSHOT_SCHEMA
    assert "CREATE EXTENSION IF NOT EXISTS vector" in database._POSTGRES_VECTOR_SCHEMA
    assert "embedding vector(768)" in database._POSTGRES_VECTOR_SCHEMA
    assert "USING hnsw (embedding vector_cosine_ops)" in database._POSTGRES_VECTOR_SCHEMA


def test_neon_cold_start_retries_fail_fail_success(monkeypatch):
    attempts = []
    delays = []

    class ConnectionError(Exception):
        pass

    def connect():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise ConnectionError("temporary connection failure")
        return "connected"

    monkeypatch.setattr(database, "_is_pg_connection_error", lambda exc: isinstance(exc, ConnectionError))
    monkeypatch.setattr(database.time, "sleep", delays.append)

    assert database._retry_pg_connection(connect) == "connected"
    assert len(attempts) == 3
    assert delays == [0.25, 0.5]


def test_retry_exhaustion_hides_driver_exception_details(monkeypatch):
    class ConnectionError(Exception):
        pass

    monkeypatch.setattr(database, "_is_pg_connection_error", lambda exc: isinstance(exc, ConnectionError))
    with pytest.raises(database.PostgresUnavailableError) as raised:
        database._retry_pg_connection(lambda: (_ for _ in ()).throw(ConnectionError("password=do-not-leak")))
    assert "do-not-leak" not in str(raised.value)


def test_development_postgres_startup_fallback_is_loud_without_periodic_probes(monkeypatch, caplog):
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", False)
    monkeypatch.setenv("JARVIS_ENV", "development")
    monkeypatch.setattr(database, "_postgres_init", Mock(side_effect=database.PostgresUnavailableError()))
    monkeypatch.setattr(database, "_sqlite_init", Mock())
    probe = Mock(side_effect=AssertionError("idle recovery must not probe Neon"))
    monkeypatch.setattr(database, "_probe_postgres", probe, raising=False)

    with caplog.at_level("ERROR", logger="jarvis.db"):
        database.init_db()

    assert database.DB_BACKEND == "sqlite"
    assert database.SQLITE_FALLBACK_ACTIVE
    assert "PostgreSQL unavailable" in caplog.text
    database._sqlite_init.assert_called_once()
    probe.assert_not_called()
    assert not hasattr(database, "_postgres_recovery_worker")


def test_production_postgres_startup_fails_closed_without_sqlite_fallback(monkeypatch):
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", False)
    monkeypatch.setenv("JARVIS_ENV", "production")
    monkeypatch.setattr(database, "_postgres_init", Mock(side_effect=database.PostgresUnavailableError()))
    monkeypatch.setattr(database, "_sqlite_init", Mock())

    with pytest.raises(database.PostgresUnavailableError, match="SQLite fallback is disabled"):
        database.init_db()

    assert database.DB_BACKEND == "postgres"
    assert not database.SQLITE_FALLBACK_ACTIVE
    database._sqlite_init.assert_not_called()


def test_postgres_dispatch_does_not_run_sqlite_legacy_adapter(monkeypatch):
    postgres_write = Mock(return_value=True)
    sqlite_write = Mock(side_effect=AssertionError("SQLite adapter must not run"))
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "_postgres_write", postgres_write)
    monkeypatch.setattr(database, "_sqlite_write", sqlite_write)

    assert database.db_write("INSERT INTO snapshots(snapshot_id,image,expires_at) VALUES(?,?,?)", ("id", b"x", "expiry"))
    postgres_write.assert_called_once()
    sqlite_write.assert_not_called()


def test_postgres_batch_dispatch_does_not_run_sqlite_legacy_adapter(monkeypatch):
    postgres_write_many = Mock(return_value=True)
    sqlite_write_many = Mock(side_effect=AssertionError("SQLite adapter must not run"))
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "_postgres_write_many", postgres_write_many)
    monkeypatch.setattr(database, "_sqlite_write_many", sqlite_write_many)

    assert database.db_write_many([("UPDATE monitors SET status=? WHERE id=?", ("up", 1))])
    postgres_write_many.assert_called_once()
    sqlite_write_many.assert_not_called()
