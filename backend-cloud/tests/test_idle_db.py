"""Simulated idle-job ticks and cache invalidation without a live database."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask

import monitor
import neural
from devices import gateway, pairing
from devices import http as devices_http
from routes import data_routes


def test_periodic_threads_issue_zero_database_calls_after_cache_warmup(monkeypatch):
    database_calls = []
    call_lock = threading.Lock()

    def read(sql, params=()):
        with call_lock:
            database_calls.append(("read", sql, params))
        return []

    def write(sql, params=()):
        with call_lock:
            database_calls.append(("write", sql, params))
        return True

    def write_many(statements):
        with call_lock:
            database_calls.append(("write_many", statements))
        return True

    monkeypatch.setattr(neural, "db_read", read)
    monkeypatch.setattr(neural, "db_write", write)
    monkeypatch.setattr(neural, "db_write_many", write_many)
    monkeypatch.setattr(monitor, "db_read", read)
    monkeypatch.setattr(monitor, "db_write", write)
    monkeypatch.setattr(monitor, "db_write_many", write_many)
    monkeypatch.setattr(monitor, "get_active_window", lambda: "Editor")

    neural.invalidate_alarm_cache()
    monitor.invalidate_monitor_cache()
    neural.refresh_alarm_cache(force=True)
    monitor.refresh_monitor_cache(force=True)
    database_calls.clear()

    monkeypatch.setattr(neural.psutil, "sensors_battery", lambda: None)
    monkeypatch.setattr(neural, "heartbeat_cfg", {**neural.heartbeat_cfg, "enabled": False})
    monkeypatch.setattr(monitor.psutil, "cpu_percent", lambda interval=1: 1)
    monkeypatch.setattr(monitor.psutil, "virtual_memory", lambda: SimpleNamespace(percent=1, used=100, total=1000))
    monkeypatch.setattr(monitor.psutil, "sensors_battery", lambda: None)
    monkeypatch.setattr(monitor.psutil, "disk_usage", lambda _path: SimpleNamespace(percent=1, used=100, total=1000))
    monkeypatch.setattr(monitor.psutil, "net_io_counters", lambda: SimpleNamespace(bytes_recv=100, bytes_sent=100))
    monkeypatch.setattr(monitor.psutil, "process_iter", lambda _fields: [])

    tick_counts = {}
    tick_lock = threading.Lock()
    loops = (
        ("SysEventMon", neural.system_event_monitor, 20),
        ("HeartbeatEngine", neural._heartbeat_thread, 10),
        ("ReminderScheduler", neural._reminder_scheduler, 10),
        ("WindowTracker", monitor.window_tracker_loop, 60),
        ("SysMonitor", monitor.monitor, 300),
        ("MonitorEngine", monitor.run_monitor_engine, 10),
    )
    real_wait = threading.Event().wait

    def simulated_sleep(_seconds):
        name = threading.current_thread().name
        with tick_lock:
            tick_counts[name] = tick_counts.get(name, 0) + 1
            target = next(target for thread_name, _loop, target in loops if thread_name == name)
            if tick_counts[name] >= target:
                raise StopTicks()
        real_wait(0.0001)

    def run_loop(loop):
        try:
            loop()
        except StopTicks:
            return

    class StopTicks(BaseException):
        pass

    monkeypatch.setattr(neural.time, "sleep", simulated_sleep)
    monkeypatch.setattr(monitor.time, "sleep", simulated_sleep)
    threads = [threading.Thread(target=run_loop, args=(loop,), name=name, daemon=True) for name, loop, _target in loops]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert all(tick_counts.get(name, 0) >= target for name, _loop, target in loops)
    assert database_calls == []

    class StopTicks(BaseException):
        pass

    def _run_for_ticks(monkeypatch, module, function, ticks=4):
        count = [0]

        def tick_sleep(_seconds):
            count[0] += 1
            if count[0] >= ticks:
                raise StopTicks()
    monkeypatch.setattr(neural, "db_read", read)
    monkeypatch.setattr(neural, "db_write", write)
    monkeypatch.setattr(neural, "db_write_many", write_many)
    monkeypatch.setattr(monitor, "db_read", read)
    monkeypatch.setattr(monitor, "db_write", write)
    monkeypatch.setattr(monitor, "db_write_many", write_many)
    monkeypatch.setattr(monitor, "get_active_window", lambda: "Editor")

    # Startup warm-up is allowed; clear its calls before simulated idle ticks.
    neural.refresh_alarm_cache(force=True)
    monitor.refresh_monitor_cache(force=True)
    database_calls.clear()

    monkeypatch.setattr(neural.psutil, "sensors_battery", lambda: None)
    monkeypatch.setattr(neural, "heartbeat_cfg", {**neural.heartbeat_cfg, "enabled": False})
    monkeypatch.setattr(monitor.psutil, "cpu_percent", lambda interval=1: 1)
    monkeypatch.setattr(monitor.psutil, "virtual_memory", lambda: SimpleNamespace(percent=1, used=100, total=1000))
    monkeypatch.setattr(monitor.psutil, "sensors_battery", lambda: None)
    monkeypatch.setattr(monitor.psutil, "disk_usage", lambda _path: SimpleNamespace(percent=1, used=100, total=1000))
    monkeypatch.setattr(monitor.psutil, "net_io_counters", lambda: SimpleNamespace(bytes_recv=100, bytes_sent=100))
    monkeypatch.setattr(monitor.psutil, "process_iter", lambda _fields: [])

    for module, function in (
        (neural, neural.system_event_monitor),
        (neural, neural._heartbeat_thread),
        (neural, neural._reminder_scheduler),
        (monitor, monitor.window_tracker_loop),
        (monitor, monitor.monitor),
        (monitor, monitor.run_monitor_engine),
    ):
        _run_for_ticks(monkeypatch, module, function)

    assert database_calls == []


def test_alarm_creation_invalidates_cache_and_new_alarm_is_loaded(monkeypatch):
    alarm_rows = []
    reads = []
    monkeypatch.setattr(neural, "db_read", lambda sql, params=(): reads.append(sql) or list(alarm_rows))
    neural.invalidate_alarm_cache()
    assert neural.refresh_alarm_cache(force=True) == []
    initial_reads = len(reads)

    app = data_routes.data
    from flask import Flask
    flask_app = Flask("alarm-cache-test")
    flask_app.register_blueprint(app)
    monkeypatch.setattr(data_routes, "db_write", lambda _sql, params=(): alarm_rows.append({
        "id": 45,
        "time": params[0],
        "label": params[1],
        "repeat": params[2],
        "active": 1,
        "status": params[4],
    }) or True)
    monkeypatch.setattr(data_routes, "add_alert", lambda _message: None)

    response = flask_app.test_client().post("/api/alarms", json={"time": "08:30", "label": "Wake"})
    assert response.status_code == 200
    assert neural.refresh_alarm_cache() == alarm_rows
    assert len(reads) == initial_reads + 1


def test_device_revoke_invalidates_cache_and_call_device_refuses_immediately(monkeypatch):
    read_count = []
    row = {"device_id": "dev-cache-test", "revoked": 0, "token_hash": "hash"}
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
    assert gateway.call_device("dev-cache-test", "open_app", {"target": "notepad"}) == {
        "ok": False,
        "error": "device_revoked",
    }


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


def test_device_status_endpoint_polls_are_served_from_cache(monkeypatch):
    reads = []
    monkeypatch.setattr(pairing, "db_read", lambda _sql, _params: reads.append(True) or [
        {"device_id": "dev-status-test", "revoked": 0}
    ])
    pairing.invalidate_device_status_cache("dev-status-test")
    app = Flask("device-status-cache-test")
    app.register_blueprint(devices_http.devices_bp)
    monkeypatch.setattr(devices_http, "EXECUTION_MODE", "remote")
    monkeypatch.setattr(devices_http, "DEVICE_ID", "dev-status-test")
    client = app.test_client()

    assert client.get("/api/device/status").get_json()["revoked"] is False
    assert client.get("/api/device/status").get_json()["revoked"] is False
    assert len(reads) == 1


def test_monitor_cache_refreshes_after_invalidation(monkeypatch):
    reads = []
    rows = [{"id": 1, "name": "first", "active": 1, "status": "running"}]
    monkeypatch.setattr(monitor, "db_read", lambda _sql: reads.append(True) or [dict(row) for row in rows])
    monitor.invalidate_monitor_cache()
    assert monitor.get_monitor_cache()[0]["name"] == "first"
    rows[:] = [{"id": 1, "name": "updated", "active": 1, "status": "running"}]
    assert monitor.get_monitor_cache()[0]["name"] == "first"
    monitor.invalidate_monitor_cache()
    assert monitor.get_monitor_cache()[0]["name"] == "updated"
    assert len(reads) == 2
