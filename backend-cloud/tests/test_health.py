"""Health endpoint database metrics are secret-free and test without Neon."""
import threading

from flask import Flask

import app.db as database
from app.routes import core_routes
from app.routes.core_routes import core


def _health_client():
    app = Flask("health-test")
    app.register_blueprint(core)
    return app.test_client()


def _live_background_threads(monkeypatch):
    names = [
        "WindowTracker", "SysMonitor", "MonitorEngine",
        "SysEventMon", "HeartbeatEngine", "ReminderScheduler",
    ]
    threads = [type("ThreadState", (), {"name": name, "is_alive": lambda self: True})() for name in names]
    monkeypatch.setattr(threading, "enumerate", lambda: threads)


def test_health_reports_neon_latency_vector_rows_and_no_connection_values(monkeypatch):
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", False)
    monkeypatch.setattr("app.routes.core_routes.db_scalar", lambda _sql: 1)
    monkeypatch.setattr("app.routes.core_routes.db_read", lambda _sql: [{"count": 17}])
    monkeypatch.setattr("psutil.cpu_percent", lambda interval=0.1: 1)
    _live_background_threads(monkeypatch)

    response = _health_client().get("/api/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["db_backend"] == "postgres"
    assert isinstance(payload["neon_select_1_latency_ms"], float)
    assert payload["pgvector_row_count"] == 17
    assert payload["sqlite_fallback_active"] is False
    assert "DATABASE_URL" not in str(payload)
    assert "password" not in str(payload).lower()


def test_health_reports_sqlite_fallback_without_neon_probe(monkeypatch):
    monkeypatch.setattr(database, "DB_BACKEND", "sqlite")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", True)
    monkeypatch.setattr("app.routes.core_routes.db_scalar", lambda _sql: 1)
    monkeypatch.setattr("app.routes.core_routes.db_read", lambda _sql: [])
    monkeypatch.setattr("psutil.cpu_percent", lambda interval=0.1: 1)
    _live_background_threads(monkeypatch)

    payload = _health_client().get("/api/health").get_json()

    assert payload["db_backend"] == "sqlite"
    assert payload["neon_select_1_latency_ms"] is None
    assert payload["pgvector_row_count"] is None
    assert payload["sqlite_fallback_active"] is True


def test_health_database_metrics_are_cached_for_30_seconds(monkeypatch):
    calls = []
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", False)
    monkeypatch.setattr(core_routes, "db_scalar", lambda _sql: calls.append("select") or 1)
    monkeypatch.setattr(core_routes, "db_read", lambda _sql: calls.append("vector_count") or [{"count": 3}])

    first = core_routes._database_health_snapshot(now=100)
    second = core_routes._database_health_snapshot(now=129.9)
    assert calls == ["select", "vector_count"]
    assert second == first

    core_routes._database_health_snapshot(now=130)
    assert calls == ["select", "vector_count", "select", "vector_count"]
