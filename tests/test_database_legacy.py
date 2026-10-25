"""Compatibility tests for legacy SQLite timestamp columns."""
import sqlite3

import pytest

import database


LEGACY_INSERTS = [
    (
        "conversations",
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, tools_used TEXT DEFAULT '', ai_model TEXT DEFAULT 'groq', timestamp TEXT NOT NULL)",
        "INSERT INTO conversations(session_id,role,content,created_at,tools_used,ai_model) VALUES(?,?,?,?,?,?)",
        ("legacy-test", "assistant", "saved", "2026-01-02 03:04:05", "", "test"),
    ),
    (
        "events",
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, message TEXT NOT NULL, timestamp TEXT NOT NULL)",
        "INSERT INTO events(type,message,created_at) VALUES(?,?,?)",
        ("test", "saved", "2026-01-02 03:04:05"),
    ),
    (
        "command_log",
        "CREATE TABLE command_log (id INTEGER PRIMARY KEY AUTOINCREMENT, command TEXT NOT NULL, result TEXT DEFAULT '', blocked INTEGER DEFAULT 0, remote INTEGER DEFAULT 0, timestamp TEXT NOT NULL)",
        "INSERT INTO command_log(command,blocked,remote,created_at) VALUES(?,?,?,?)",
        ("open_app", 0, 1, "2026-01-02 03:04:05"),
    ),
    (
        "notes",
        "CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL, updated_at TEXT NOT NULL, timestamp TEXT NOT NULL)",
        "INSERT INTO notes(title,content,created_at,updated_at) VALUES(?,?,?,?)",
        ("title", "content", "2026-01-02 03:04:05", "2026-01-03 03:04:05"),
    ),
    (
        "alarms",
        "CREATE TABLE alarms (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, label TEXT NOT NULL DEFAULT 'Reminder', repeat TEXT NOT NULL DEFAULT 'once', active INTEGER NOT NULL DEFAULT 1, trigger_time TEXT DEFAULT '', status TEXT DEFAULT 'pending', retry_count INTEGER DEFAULT 0, timestamp TEXT NOT NULL)",
        "INSERT INTO alarms(time,label,repeat,active,created_at,status) VALUES(?,?,?,1,?,?)",
        ("08:30", "Wake", "once", "2026-01-02 03:04:05", "pending"),
    ),
    (
        "heartbeat_log",
        "CREATE TABLE heartbeat_log (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL, message TEXT NOT NULL, priority TEXT DEFAULT 'medium', delivered INTEGER DEFAULT 0, timestamp TEXT NOT NULL)",
        "INSERT INTO heartbeat_log(trigger,message,priority,delivered,created_at) VALUES(?,?,?,?,?)",
        ("idle", "break", "low", 0, "2026-01-02 03:04:05"),
    ),
    (
        "memory_facts",
        "CREATE TABLE memory_facts (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, fact TEXT NOT NULL, source TEXT DEFAULT 'learned', last_used TEXT DEFAULT '', timestamp TEXT NOT NULL)",
        "INSERT INTO memory_facts(category,fact,source,created_at,last_used) VALUES(?,?,?,?,?)",
        ("general", "fact", "test", "2026-01-02 03:04:05", ""),
    ),
]


@pytest.mark.parametrize("table,legacy_schema,insert_sql,params", LEGACY_INSERTS)
def test_legacy_required_timestamp_is_filled(tmp_path, monkeypatch, table, legacy_schema, insert_sql, params):
    database_path = tmp_path / f"{table}.db"
    with sqlite3.connect(database_path) as connection:
        schema_with_legacy_fields = legacy_schema[:-1] + ", legacy_text TEXT NOT NULL, legacy_count INTEGER NOT NULL)"
        connection.execute(schema_with_legacy_fields)

    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setattr(database, "DB_BACKEND", "sqlite")
    database._sqlite_init()

    assert database.db_write(insert_sql, params)
    rows = database.db_read(
        f"SELECT created_at,timestamp,legacy_text,legacy_count FROM {table} ORDER BY id DESC LIMIT 1"
    )
    assert rows
    assert rows[0]["timestamp"] == rows[0]["created_at"]
    assert rows[0]["legacy_text"] == ""
    assert rows[0]["legacy_count"] == 0