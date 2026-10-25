import atexit
import os
import socket
import tempfile

import psycopg2
import pytest
import requests

_TEST_DATA_DIR = tempfile.TemporaryDirectory(prefix="jarvis-tests-")
atexit.register(_TEST_DATA_DIR.cleanup)

os.environ["JARVIS_SKIP_DOTENV"] = "1"
os.environ["JARVIS_DATA_DIR"] = _TEST_DATA_DIR.name
os.environ["DB_BACKEND"] = "sqlite"
os.environ["GROQ_KEY"] = "test-groq-key"
os.environ["GEMINI_KEY"] = "test-gemini-key"
os.environ["OPENROUTER_KEY"] = "test-openrouter-key"
os.environ["WEATHER_KEY"] = "test-weather-key"
os.environ["FLASK_SECRET"] = "test-only-secret"

from app.db import init_db

init_db()


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
	def reject_connection(*_args, **_kwargs):
		raise AssertionError("External network access is disabled in backend tests")

	monkeypatch.setattr(socket, "create_connection", reject_connection)
	monkeypatch.setattr(socket.socket, "connect", reject_connection)
	monkeypatch.setattr(psycopg2, "connect", reject_connection)
	monkeypatch.setattr(requests.sessions.Session, "request", reject_connection)
