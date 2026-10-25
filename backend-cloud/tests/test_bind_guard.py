import logging

import pytest

from app.config import resolve_bind_host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20"])
def test_public_bind_is_refused_by_default(host, monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_BIND", raising=False)

    with pytest.raises(RuntimeError, match="Refusing non-loopback JARVIS_HOST"):
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
