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
_monitor_cache: dict[str, list[dict]] = {}
_monitor_cache_synced_at: dict[str, float] = {}
_monitor_db_state: dict[tuple[str, int], dict] = {}
_monitor_owners: list[str] | None = None
_monitor_owners_synced_at = 0.0


def refresh_monitor_owners(force: bool = False, now: float | None = None) -> list[str]:
    global _monitor_owners, _monitor_owners_synced_at
    instant = time.monotonic() if now is None else now
    with _monitor_cache_lock:
        if _monitor_owners is not None and not force:
            return list(_monitor_owners)
    rows = db_read("SELECT owner_username FROM user_owners ORDER BY owner_username")
    owners = sorted({
        str(row["owner_username"]) for row in rows if row.get("owner_username")
    })
    with _monitor_cache_lock:
        _monitor_owners = owners
        _monitor_owners_synced_at = instant
    return list(owners)


def refresh_all_monitor_caches(force: bool = False, now: float | None = None) -> None:
    for owner in refresh_monitor_owners(force=force, now=now):
        refresh_monitor_cache(owner, force=force, now=now)


def refresh_monitor_cache(owner_username: str = "", force: bool = False,
                          now: float | None = None) -> list[dict]:
    instant = time.monotonic() if now is None else now
    with _monitor_cache_lock:
        if (owner_username in _monitor_cache and not force
                and instant - _monitor_cache_synced_at.get(owner_username, 0.0) < MONITOR_CACHE_TTL_SECONDS):
            return [dict(monitor) for monitor in _monitor_cache[owner_username]]
        monitors = db_read(
            "SELECT * FROM monitors WHERE owner_username=? ORDER BY id ASC", (owner_username,)
        )
        _monitor_cache[owner_username] = [dict(monitor) for monitor in monitors]
        _monitor_cache_synced_at[owner_username] = instant
        for key in [key for key in _monitor_db_state if key[0] == owner_username]:
            del _monitor_db_state[key]
        _monitor_db_state.update({
            (owner_username, monitor["id"]): {
                "persisted_status": monitor.get("status", ""),
                "last_write": instant,
                "pending_trigger_count": 0,
            }
            for monitor in _monitor_cache[owner_username] if monitor.get("id") is not None
        })
        return [dict(monitor) for monitor in _monitor_cache[owner_username]]


def invalidate_monitor_cache(owner_username: str | None = None) -> None:
    global _monitor_owners, _monitor_owners_synced_at
    with _monitor_cache_lock:
        if owner_username is None:
            _monitor_cache.clear()
            _monitor_cache_synced_at.clear()
            _monitor_db_state.clear()
            _monitor_owners = None
            _monitor_owners_synced_at = 0.0
        else:
            _monitor_cache.pop(owner_username, None)
            _monitor_cache_synced_at.pop(owner_username, None)
            for key in [key for key in _monitor_db_state if key[0] == owner_username]:
                del _monitor_db_state[key]
            if _monitor_owners is not None and owner_username not in _monitor_owners:
                _monitor_owners.append(owner_username)
                _monitor_owners_synced_at = time.monotonic()


def forget_monitor_owner(owner_username: str) -> None:
    global _monitor_owners
    invalidate_monitor_cache(owner_username)
    with _monitor_cache_lock:
        if _monitor_owners is not None:
            _monitor_owners = [owner for owner in _monitor_owners if owner != owner_username]


def get_monitor_cache(owner_username: str = "") -> list[dict]:
    return refresh_monitor_cache(owner_username)


def _record_monitor_check(
    monitor: dict,
    status: str,
    last_check: str,
    result: str,
    alert_sent: int,
    increment_trigger_count: bool,
) -> None:
    owner_username = str(monitor.get("owner_username") or "")
    monitor_id = monitor.get("id")
    if monitor_id is None:
        return
    with _monitor_cache_lock:
        cached = next(
            (
                item for item in _monitor_cache.get(owner_username, [])
                if item.get("id") == monitor_id
            ),
            None,
        )
        if cached is None:
            if owner_username not in _monitor_cache:
                return
            cached = dict(monitor)
            _monitor_cache[owner_username].append(cached)
        state = _monitor_db_state.setdefault((owner_username, monitor_id), {
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
                "UPDATE monitors SET status=?,last_check=?,trigger_count=trigger_count+? WHERE id=? AND owner_username=?",
                (status, last_check, state["pending_trigger_count"], monitor_id, owner_username),
            )
        else:
            update = (
                "UPDATE monitors SET status=?,last_check=? WHERE id=? AND owner_username=?",
                (status, last_check, monitor_id, owner_username),
            )
        writes = [update, (
            "INSERT INTO monitor_log(owner_username,monitor_id,monitor_name,result,alert_sent,timestamp)"
            " VALUES(?,?,?,?,?,?)",
            (owner_username, monitor_id, monitor.get("name", ""), result, alert_sent, last_check),
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
            add_alert(
                f"Monitor DOWN: {name} (HTTP {response.status_code})",
                owner_username=str(monitor.get("owner_username") or ""),
            )
            threading.Thread(
                target=send_discord_alert,
                args=(f"JARVIS Monitor: {name} is DOWN", None,
                      str(monitor.get("owner_username") or "")),
                daemon=True,
            ).start()
    except Exception as exc:
        _record_monitor_check(
            monitor, "error", ts(), type(exc).__name__, 0, False,
        )
        log.error("Monitor check '%s': %s", name, exc)


def monitor_engine_tick() -> None:
    for owner in refresh_monitor_owners():
        monitors = [
            monitor for monitor in refresh_monitor_cache(owner)
            if monitor.get("active", 1) and monitor.get("status") != "paused"
        ]
        for monitor in monitors:
            threading.Thread(target=check_monitor, args=(monitor,), daemon=True).start()


def run_monitor_engine() -> None:
    global monitor_engine_running
    monitor_engine_running = True
    log.info("HTTP monitor engine started")
    refresh_all_monitor_caches()
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
