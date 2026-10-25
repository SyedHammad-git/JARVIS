"""Compatibility tests for legacy SQLite timestamp columns."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


class LegacyTimestampTests(unittest.TestCase):
    def test_conversations_and_events_fill_required_legacy_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            connection.executescript("""
                CREATE TABLE conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)
            connection.close()

            with patch.object(database, "DB_PATH", database_path), \
                 patch.object(database, "DB_BACKEND", "sqlite"):
                database._sqlite_init()
                created_at = database.ts()
                self.assertTrue(database.db_write(
                    "INSERT INTO conversations(session_id,role,content,created_at,tools_used,ai_model) "
                    "VALUES(?,?,?,?,?,?)",
                    ("legacy-test", "assistant", "saved", created_at, "", "test"),
                ))
                self.assertTrue(database.db_write(
                    "INSERT INTO events(type,message,created_at) VALUES(?,?,?)",
                    ("test", "saved", created_at),
                ))
                conversation = database.db_read(
                    "SELECT created_at,timestamp FROM conversations WHERE session_id=?",
                    ("legacy-test",),
                )[0]
                event = database.db_read(
                    "SELECT created_at,timestamp FROM events WHERE type=?",
                    ("test",),
                )[0]

            self.assertEqual(conversation["timestamp"], created_at)
            self.assertEqual(event["timestamp"], created_at)


if __name__ == "__main__":
    unittest.main()