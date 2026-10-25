import logging
import os
from pathlib import Path

import pytest

from app.config import resolve_bind_host
from app.db import DATA_DIR


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20"])
def test_public_bind_is_refused_by_default(host, monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_BIND", raising=False)

    with pytest.raises(RuntimeError, match="Set JARVIS_HOST=127.0.0.1 in backend-cloud/.env"):
        resolve_bind_host(host)


def test_public_bind_requires_explicit_opt_in_and_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="jarvis.config"):
        host = resolve_bind_host("0.0.0.0", allow_public="1")

    assert host == "0.0.0.0"
    assert "PUBLIC BIND ENABLED" in caplog.text


def test_default_bind_is_loopback(monkeypatch):
    monkeypatch.delenv("JARVIS_HOST", raising=False)
    monkeypatch.delenv("ALLOW_PUBLIC_BIND", raising=False)

    assert resolve_bind_host() == "127.0.0.1"


def test_factory_rejects_public_bind_before_database_initialization(monkeypatch):
    import app
    from app import db

    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    monkeypatch.delenv("ALLOW_PUBLIC_BIND", raising=False)
    monkeypatch.setattr(db, "init_db", lambda: pytest.fail("database initialized before bind validation"))

    with pytest.raises(RuntimeError, match="Set JARVIS_HOST=127.0.0.1 in backend-cloud/.env"):
        app.create_app(testing=False)


def test_backend_tests_skip_dotenv_and_use_temporary_data_dir():
    assert os.environ["JARVIS_SKIP_DOTENV"] == "1"
    assert DATA_DIR == Path(os.environ["JARVIS_DATA_DIR"])
    assert DATA_DIR.name.startswith("jarvis-tests-")


def test_non_testing_startup_logs_presence_only_self_check(monkeypatch, caplog):
    import app
    from app import monitor, neural
    from app.vision import snapshots

    monkeypatch.setenv("JARVIS_HOST", "127.0.0.1")
    monkeypatch.setenv("ALLOW_PUBLIC_BIND", "0")
    monkeypatch.setattr(monitor, "start_background_threads", lambda: None)
    monkeypatch.setattr(neural, "start_background_threads", lambda: None)
    monkeypatch.setattr(snapshots, "cleanup_snapshots", lambda: None)

    with caplog.at_level(logging.INFO):
        app.create_app(testing=False)

    assert "provider_key_presence groq=True gemini=True openrouter=True weather=True" in caplog.text
    assert "db_backend=sqlite bind_host=127.0.0.1 auth_enabled=no" in caplog.text
    assert "SECURITY WARNING: API authentication is disabled" in caplog.text
    assert "test-groq-key" not in caplog.text
    assert "test-gemini-key" not in caplog.text
    assert "test-openrouter-key" not in caplog.text
