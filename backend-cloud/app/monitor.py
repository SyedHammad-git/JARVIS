"""HTTP uptime monitors with a bounded in-memory database cache."""
from __future__ import annotations

import json
import logging
import threading
import time
from threading import Lock

from app.auth import add_alert
from app.config import REQUESTS_OK, _req
from app.db import db_read, db_write_many, ts
from app.notifications import send_discord_alert

log = logging.getLogger("jarvis.monitor")

monitor_engine_running = False
MONITOR_CACHE_TTL_SECONDS = 30 * 60
MONITOR_DB_HEARTBEAT_SECONDS = 15 * 60
_monitor_cache_lock = Lock()
_monitor_cache: list[dict] | None = None
_monitor_cache_synced_at = 0.0
_monitor_db_state: dict[int, dict] = {}


def refresh_monitor_cache(force: bool = False, now: float | None = None) -> list[dict]:
    global _monitor_cache, _monitor_cache_synced_at, _monitor_db_state
    instant = time.monotonic() if now is None else now
    with _monitor_cache_lock:
        if (_monitor_cache is not None and not force
                and instant - _monitor_cache_synced_at < MONITOR_CACHE_TTL_SECONDS):
            return [dict(monitor) for monitor in _monitor_cache]
        monitors = db_read("SELECT * FROM monitors ORDER BY id ASC")
        _monitor_cache = [dict(monitor) for monitor in monitors]
        _monitor_cache_synced_at = instant
        _monitor_db_state = {
            monitor["id"]: {
                "persisted_status": monitor.get("status", ""),
                "last_write": instant,
                "pending_trigger_count": 0,
            }
            for monitor in _monitor_cache if monitor.get("id") is not None
        }
        return [dict(monitor) for monitor in _monitor_cache]


def invalidate_monitor_cache() -> None:
    global _monitor_cache, _monitor_cache_synced_at
    with _monitor_cache_lock:
        _monitor_cache = None
        _monitor_cache_synced_at = 0.0


def get_monitor_cache() -> list[dict]:
    return refresh_monitor_cache()


def _record_monitor_check(
    monitor: dict,
    status: str,
    last_check: str,
    result: str,
    alert_sent: int,
    increment_trigger_count: bool,
) -> None:
    monitor_id = monitor.get("id")
    if monitor_id is None:
        return
    with _monitor_cache_lock:
        cached = next(
            (item for item in (_monitor_cache or []) if item.get("id") == monitor_id),
            None,
        )
        if cached is None:
            if _monitor_cache is None:
                return
            cached = dict(monitor)
            _monitor_cache.append(cached)
        state = _monitor_db_state.setdefault(monitor_id, {
            "persisted_status": monitor.get("status", ""),
            "last_write": time.monotonic(),
            "pending_trigger_count": 0,
        })
        cached["status"] = status
        cached["last_check"] = last_check
        if increment_trigger_count:
            cached["trigger_count"] = int(cached.get("trigger_count") or 0) + 1
            state["pending_trigger_count"] += 1

        now = time.monotonic()
        state_changed = status != state["persisted_status"]
        heartbeat_due = now - state["last_write"] >= MONITOR_DB_HEARTBEAT_SECONDS
        if not state_changed and not heartbeat_due:
            return

        if increment_trigger_count:
            update = (
                "UPDATE monitors SET status=?,last_check=?,trigger_count=trigger_count+? WHERE id=?",
                (status, last_check, state["pending_trigger_count"], monitor_id),
            )
        else:
            update = (
                "UPDATE monitors SET status=?,last_check=? WHERE id=?",
                (status, last_check, monitor_id),
            )
        writes = [update, (
            "INSERT INTO monitor_log(monitor_id,monitor_name,result,alert_sent,created_at)"
            " VALUES(?,?,?,?,?)",
            (monitor_id, monitor.get("name", ""), result, alert_sent, last_check),
        )]
        if db_write_many(writes):
            state["persisted_status"] = status
            state["last_write"] = now
            state["pending_trigger_count"] = 0


def check_monitor(monitor: dict) -> None:
    """Run one configured HTTP(S) uptime check."""
    monitor_id = monitor.get("id")
    name = monitor.get("name", "")
    monitor_type = monitor.get("type", "http")
    try:
        config = json.loads(monitor.get("config", "{}") or "{}")
    except (json.JSONDecodeError, TypeError):
        config = {}
    url = config.get("url", "")
    timeout = int(config.get("timeout", 10))
    if monitor_type not in {"http", "https"}:
        log.warning("Monitor %s uses an unsupported type; only HTTP checks run", monitor_id)
        return
    if not url or not REQUESTS_OK:
        log.warning("Monitor %s has no URL or HTTP client; skipping", monitor_id)
        return

    try:
        started = time.time()
        response = _req.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "JARVIS-Monitor/17.0"},
        )
        elapsed = round((time.time() - started) * 1000)
        status = "up" if response.status_code < 500 else "down"
        result = f"HTTP {response.status_code} in {elapsed}ms"
        now = ts()
        _record_monitor_check(
            monitor, status, now, result, 0 if status == "up" else 1, True,
        )
        if status == "down":
            add_alert(f"Monitor DOWN: {name} (HTTP {response.status_code})")
            threading.Thread(
                target=send_discord_alert,
                args=(f"JARVIS Monitor: {name} is DOWN",),
                daemon=True,
            ).start()
    except Exception as exc:
        _record_monitor_check(
            monitor, "error", ts(), type(exc).__name__, 0, False,
        )
        log.error("Monitor check '%s': %s", name, exc)


def monitor_engine_tick() -> None:
    monitors = [
        monitor for monitor in refresh_monitor_cache()
        if monitor.get("active", 1) and monitor.get("status") != "paused"
    ]
    for monitor in monitors:
        threading.Thread(target=check_monitor, args=(monitor,), daemon=True).start()


def run_monitor_engine() -> None:
    global monitor_engine_running
    monitor_engine_running = True
    log.info("HTTP monitor engine started")
    refresh_monitor_cache()
    while True:
        try:
            monitor_engine_tick()
        except Exception as exc:
            log.error("Monitor engine: %s", exc)
        time.sleep(60)


def start_background_threads() -> None:
    threading.Thread(
        target=run_monitor_engine,
        daemon=True,
        name="MonitorEngine",
    ).start()
