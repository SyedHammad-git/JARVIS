"""Verify cached scheduled work, cache invalidation, and device revocation."""
from __future__ import annotations

from unittest.mock import Mock

from flask import Flask, g

import app.monitor as monitor
import app.neural as neural
from app.devices import gateway, pairing
from app.devices import http as devices_http
from app.routes import data_routes


def test_periodic_threads_use_warm_caches_without_idle_database_calls(monkeypatch):
    calls = []
    read = lambda sql, params=(): calls.append(("read", sql, params)) or []
    monkeypatch.setattr(neural, "db_read", read)
    monkeypatch.setattr(monitor, "db_read", read)
    monkeypatch.setattr(neural, "db_write_many", lambda statements: calls.append(("write", statements)) or True)
    monkeypatch.setattr(monitor, "db_write_many", lambda statements: calls.append(("write", statements)) or True)

    neural.invalidate_alarm_cache()
    monitor.invalidate_monitor_cache()
    neural.refresh_alarm_owners(force=True)
    monitor.refresh_monitor_owners(force=True)
    neural.refresh_all_alarm_caches(force=True)
    monitor.refresh_all_monitor_caches(force=True)
    calls.clear()
    monkeypatch.setattr(neural, "heartbeat_cfg", {**neural.heartbeat_cfg, "enabled": False})

    class StopTicks(BaseException):
        pass

    for module, function in (
        (neural, neural._heartbeat_thread),
        (neural, neural._reminder_scheduler),
        (monitor, monitor.run_monitor_engine),
    ):
        ticks = [0]

        def stop_after_tick(_seconds):
            ticks[0] += 1
            if ticks[0] >= 4:
                raise StopTicks()

        monkeypatch.setattr(module.time, "sleep", stop_after_tick)
        try:
            function()
        except StopTicks:
            pass

    assert calls == []


def test_alarm_creation_invalidates_cache_and_new_alarm_is_loaded(monkeypatch):
    alarm_rows = []
    reads = []
    monkeypatch.setattr(neural, "db_read", lambda sql, params=(): reads.append(sql) or list(alarm_rows))
    neural.invalidate_alarm_cache()
    assert neural.refresh_alarm_cache(force=True) == []
    initial_reads = len(reads)

    flask_app = Flask("alarm-cache-test")
    flask_app.register_blueprint(data_routes.data)

    def insert_alarm(_sql, params=()):
        alarm_rows.append({
            "id": 45,
            "owner_username": params[0],
            "time": params[1],
            "label": params[2],
            "repeat": params[3],
            "active": 1,
            "status": params[5],
        })
        return True

    monkeypatch.setattr(data_routes, "db_write", insert_alarm)
    monkeypatch.setattr(data_routes, "add_alert", lambda _message, **_kwargs: None)

    @flask_app.before_request
    def authenticate_alarm_owner():
        g.current_user = {"username": "owner-a"}

    response = flask_app.test_client().post(
        "/api/alarms", json={"time": "08:30", "label": "Wake"},
    )
    assert response.status_code == 200
    assert neural.refresh_alarm_cache("owner-a") == alarm_rows
    assert len(reads) == initial_reads + 1


def test_device_revoke_invalidates_cache_and_call_device_refuses_immediately(monkeypatch):
    read_count = []
    row = {
        "device_id": "dev-cache-test",
        "revoked": 0,
        "token_hash": "hash",
        "owner_username": "owner",
        "scopes": '{"allow_open_app": true}',
    }
    monkeypatch.setattr(pairing, "db_read", lambda _sql, _params: read_count.append(True) or [dict(row)])
    monkeypatch.setattr(pairing, "get_device", lambda _device_id: dict(row))
    monkeypatch.setattr(pairing, "db_write", lambda _sql, _params: True)
    monkeypatch.setattr(gateway, "disconnect_device", Mock())
    monkeypatch.setattr(gateway, "socketio", Mock())
    pairing.invalidate_device_status_cache("dev-cache-test")

    assert pairing.get_device_status_cached("dev-cache-test")["revoked"] == 0
    assert len(read_count) == 1
    row["revoked"] = 1
    assert pairing.revoke_device("dev-cache-test")
    assert pairing.get_device_status_cached("dev-cache-test")["revoked"] == 1
    assert len(read_count) == 1
    assert gateway.call_device(
        "dev-cache-test",
        "open_app",
        {"target": "notepad"},
        owner_username="owner",
    ) == {"ok": False, "error": "device_revoked"}


def test_device_status_cache_requeries_only_after_sixty_seconds(monkeypatch):
    now = [100.0]
    reads = []
    row = {"device_id": "dev-ttl-test", "revoked": 0}
    monkeypatch.setattr(pairing.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(pairing, "db_read", lambda _sql, _params: reads.append(True) or [dict(row)])
    pairing.invalidate_device_status_cache("dev-ttl-test")

    assert pairing.get_device_status_cached("dev-ttl-test")["revoked"] == 0
    now[0] += 59
    assert pairing.get_device_status_cached("dev-ttl-test")["revoked"] == 0
    assert len(reads) == 1
    now[0] += 1
    assert pairing.get_device_status_cached("dev-ttl-test")["revoked"] == 0
    assert len(reads) == 2


def test_device_status_endpoint_reports_online_state_without_execution_mode(monkeypatch):
    reads = []
    monkeypatch.setattr(pairing, "db_read", lambda _sql, _params: reads.append(True) or [
        {"device_id": "dev-status-test", "revoked": 0}
    ])
    pairing.invalidate_device_status_cache("dev-status-test")
    app = Flask("device-status-cache-test")
    app.register_blueprint(devices_http.devices_bp)
    monkeypatch.setattr(devices_http, "DEVICE_ID", "dev-status-test")
    monkeypatch.setattr(devices_http, "get_device", lambda _device_id: {
        "device_id": "dev-status-test",
        "owner_username": "status-owner",
        "token_hash": "test-hash",
    })
    monkeypatch.setattr(devices_http, "is_online", lambda _device_id: True)

    @app.before_request
    def authenticate_status_owner():
        g.current_user = {"username": "status-owner"}

    client = app.test_client()
    first = client.get("/api/device/status").get_json()
    second = client.get("/api/device/status").get_json()
    assert first["online"] is True
    assert first["label"] == "online"
    assert "execution_mode" not in first
    assert second["online"] is True
    assert len(reads) == 1


def test_monitor_cache_refreshes_after_invalidation(monkeypatch):
    reads = []
    rows = [{"id": 1, "name": "first", "active": 1, "status": "running"}]
    monkeypatch.setattr(
        monitor,
        "db_read",
        lambda _sql, _params=(): reads.append(True) or [dict(row) for row in rows],
    )
    monitor.invalidate_monitor_cache()
    assert monitor.get_monitor_cache()[0]["name"] == "first"
    rows[:] = [{"id": 1, "name": "updated", "active": 1, "status": "running"}]
    assert monitor.get_monitor_cache()[0]["name"] == "first"
    monitor.invalidate_monitor_cache()
    assert monitor.get_monitor_cache()[0]["name"] == "updated"
    assert len(reads) == 2
