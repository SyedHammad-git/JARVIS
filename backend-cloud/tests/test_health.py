"""Health endpoints report backend and database status without host statistics."""
from flask import Flask

import app.db as database
from app.routes import core_routes
from app.routes.core_routes import core


def _health_client():
    app = Flask("health-test")
    app.register_blueprint(core)
    return app.test_client()


def _invalidate_health_cache():
    core_routes._db_health_cache["payload"] = None


def test_health_reports_neon_latency_vector_count_and_online_devices(monkeypatch):
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", False)
    monkeypatch.setattr(core_routes, "db_scalar", lambda _sql: 1)

    def read(sql, _params=()):
        if "memory_vectors" in sql:
            return [{"count": 17}]
        if "FROM devices" in sql:
            return [{"device_id": "dev-online"}, {"device_id": "dev-offline"}]
        return []

    monkeypatch.setattr(core_routes, "db_read", read)
    monkeypatch.setattr(
        "app.devices.gateway.is_online",
        lambda device_id: device_id == "dev-online",
    )
    monkeypatch.setattr(
        "app.devices.gateway.online_device_ids",
        lambda: ["dev-online"],
    )
    _invalidate_health_cache()

    client = _health_client()
    payload = client.get("/api/health").get_json()
    details = client.get("/api/health/details").get_json()

    assert payload["status"] == "ok"
    assert payload["db_backend"] == "postgres"
    assert isinstance(payload["neon_select_1_latency_ms"], float)
    assert payload["pgvector_row_count"] == 17
    assert payload["sqlite_fallback_active"] is False
    assert payload["online_device_count"] == 1
    assert "DATABASE_URL" not in str(payload)
    assert "password" not in str(payload).lower()
    assert "cpu_pct" not in client.get("/api/sysinfo").get_json()
    assert details["online_device_count"] == 1


def test_health_reports_sqlite_fallback_without_neon_probe(monkeypatch):
    monkeypatch.setattr(database, "DB_BACKEND", "sqlite")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", True)
    monkeypatch.setattr(core_routes, "db_scalar", lambda _sql: 1)
    monkeypatch.setattr(core_routes, "db_read", lambda _sql, _params=(): [])
    _invalidate_health_cache()

    payload = _health_client().get("/api/health").get_json()

    assert payload["db_backend"] == "sqlite"
    assert payload["neon_select_1_latency_ms"] is None
    assert payload["pgvector_row_count"] is None
    assert payload["sqlite_fallback_active"] is True
    assert payload["online_device_count"] == 0


def test_health_database_metrics_are_cached_for_30_seconds(monkeypatch):
    calls = []
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "SQLITE_FALLBACK_ACTIVE", False)
    monkeypatch.setattr(core_routes, "db_scalar", lambda _sql: calls.append("select") or 1)
    monkeypatch.setattr(
        core_routes,
        "db_read",
        lambda _sql, _params=(): calls.append("vector_count") or [{"count": 3}],
    )

    first = core_routes._database_health_snapshot(now=100)
    second = core_routes._database_health_snapshot(now=129.9)
    assert calls == ["select", "vector_count"]
    assert second == first

    core_routes._database_health_snapshot(now=130)
    assert calls == ["select", "vector_count", "select", "vector_count"]
