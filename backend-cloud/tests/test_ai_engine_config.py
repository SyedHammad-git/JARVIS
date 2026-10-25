import importlib
import logging
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from app.ai import agent, engine


class _Response:
    status_code = 200

    def json(self):
        return {
            "choices": [{"message": {"content": "mock reply"}}],
            "candidates": [{"content": {"parts": [{"text": "mock reply"}]}}],
        }


@pytest.mark.parametrize(
    ("key_name", "call", "expected_header"),
    [
        ("GROQ_KEY", lambda: engine.call_groq([]), "Authorization"),
        ("OPENROUTER_KEY", lambda: engine.call_openrouter([]), "Authorization"),
        ("GEMINI_KEY", lambda: engine.call_gemini("mock prompt"), None),
    ],
)
def test_provider_reads_key_from_environment_at_call_time(
    monkeypatch, key_name, call, expected_header
):
    key = "call-time-test-key"
    monkeypatch.setattr(engine.app_config, key_name, "")
    monkeypatch.setenv(key_name, key)
    captured = {}

    def fake_post(url, headers=None, **_kwargs):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _Response()

    monkeypatch.setattr(engine, "_post_with_retry", fake_post)

    result = call()

    assert result["ok"] is True
    if expected_header:
        assert captured["headers"][expected_header] == f"Bearer {key}"
    else:
        assert parse_qs(urlsplit(captured["url"]).query)["key"] == [key]


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_provider_http_failures_log_provider_and_status(
    monkeypatch, caplog, status_code
):
    class ErrorResponse(_Response):
        text = "first line: api_key=do-not-log\nsecond line"

    response = ErrorResponse()
    response.status_code = status_code
    monkeypatch.setenv("GROQ_KEY", "mock-groq-key")
    monkeypatch.setattr(engine, "_post_with_retry", lambda *_args, **_kwargs: response)

    with caplog.at_level(logging.WARNING, logger="jarvis.ai"):
        result = engine.call_groq([])

    assert result["ok"] is False
    assert f"provider=groq exception_class=HTTPError http_status={status_code}" in caplog.text
    assert "do-not-log" not in caplog.text
    assert "second line" not in caplog.text


def test_provider_timeout_logs_exception_class_without_key(
    monkeypatch, caplog
):
    monkeypatch.setenv("GROQ_KEY", "mock-groq-key")

    def timeout(*_args, **_kwargs):
        raise requests.Timeout("request timed out")

    monkeypatch.setattr(engine, "_post_with_retry", timeout)

    with caplog.at_level(logging.WARNING, logger="jarvis.ai"):
        result = engine.call_groq([])

    assert result["ok"] is False
    assert "provider=groq exception_class=Timeout http_status=none" in caplog.text
    assert "mock-groq-key" not in caplog.text


def test_engine_agent_and_config_use_one_module_identity():
    config_module = importlib.import_module("app.config")

    assert engine.app_config is config_module
    assert sys.modules["app.config"] is config_module
    assert agent.chat is engine.chat
