"""In-memory cached alarm scheduler and service-side heartbeat."""
from __future__ import annotations

import datetime
import logging
import threading
import time
from threading import Lock

from app.config import heartbeat_cfg, heartbeat_lock
from app.db import db_read, db_write_many, ts
from app.notifications import send_os_notification
from app.ai.engine import groq_as_manager

log = logging.getLogger("jarvis.neural")

neural_lock = Lock()
neural_state = {
    "active": False,
    "mode": "normal",
    "conv_state": "idle",
    "last_cmd": "",
    "last_reply": "",
    "alerts": [],
    "event_queue": [],
}
_owner_neural_states: dict[str, dict] = {}


def owner_neural_state(owner_username: str) -> dict:
    return _owner_neural_states.setdefault(owner_username, {
        "active": False,
        "mode": "normal",
        "conv_state": "idle",
        "last_cmd": "",
        "last_reply": "",
        "alerts": [],
    })

_ALARM_CACHE_TTL = 30 * 60
_alarm_cache_lock = Lock()
_alarm_cache: dict[str, list[dict]] = {}
_alarm_cache_synced_at: dict[str, float] = {}
_alarm_owners: list[str] | None = None
_alarm_owners_synced_at = 0.0
_heartbeat_states: dict[str, dict] = {}
_heartbeat_queues: dict[str, list[dict]] = {}


def register_heartbeat_owner(owner_username: str) -> None:
    if not owner_username:
        return
    with heartbeat_lock:
        _heartbeat_states.setdefault(owner_username, {
            "config": dict(heartbeat_cfg),
            "session": {
                "start": time.time(), "break_reminded": False, "last_break_remind": 0.0,
            },
        })
        _heartbeat_queues.setdefault(owner_username, [])


def get_heartbeat_config(owner_username: str) -> dict:
    register_heartbeat_owner(owner_username)
    with heartbeat_lock:
        return dict(_heartbeat_states[owner_username]["config"])


def update_heartbeat_config(owner_username: str, updates: dict) -> dict:
    register_heartbeat_owner(owner_username)
    with heartbeat_lock:
        config = _heartbeat_states[owner_username]["config"]
        config.update(updates)
        return dict(config)


def get_heartbeat_queue(owner_username: str, *, clear: bool = False) -> list[dict]:
    register_heartbeat_owner(owner_username)
    with heartbeat_lock:
        queue = list(_heartbeat_queues[owner_username])
        if clear:
            _heartbeat_queues[owner_username].clear()
        return queue


def purge_owner_state(owner_username: str) -> None:
    with heartbeat_lock:
        _heartbeat_states.pop(owner_username, None)
        _heartbeat_queues.pop(owner_username, None)
    with neural_lock:
        _owner_neural_states.pop(owner_username, None)
        neural_state["event_queue"] = [
            event for event in neural_state["event_queue"]
            if event.get("owner_username") != owner_username
        ]


def refresh_alarm_owners(force: bool = False, now: float | None = None) -> list[str]:
    global _alarm_owners, _alarm_owners_synced_at
    instant = time.monotonic() if now is None else now
    with _alarm_cache_lock:
        if _alarm_owners is not None and not force:
            return list(_alarm_owners)
    rows = db_read("SELECT owner_username FROM user_owners ORDER BY owner_username")
    owners = sorted({
        str(row["owner_username"]) for row in rows if row.get("owner_username")
    })
    with _alarm_cache_lock:
        _alarm_owners = owners
        _alarm_owners_synced_at = instant
    return list(owners)


def refresh_all_alarm_caches(force: bool = False, now: float | None = None) -> None:
    for owner in refresh_alarm_owners(force=force, now=now):
        refresh_alarm_cache(owner, force=force, now=now)


def refresh_alarm_cache(owner_username: str = "", force: bool = False,
                        now: float | None = None) -> list[dict]:
    instant = time.monotonic() if now is None else now
    with _alarm_cache_lock:
        if (owner_username in _alarm_cache and not force
                and instant - _alarm_cache_synced_at.get(owner_username, 0.0) < _ALARM_CACHE_TTL):
            return [dict(alarm) for alarm in _alarm_cache[owner_username]]
        _alarm_cache[owner_username] = db_read(
            "SELECT * FROM alarms WHERE owner_username=? AND active=1 ORDER BY time ASC",
            (owner_username,),
        )
        _alarm_cache_synced_at[owner_username] = instant
        return [dict(alarm) for alarm in _alarm_cache[owner_username]]


def invalidate_alarm_cache(owner_username: str | None = None) -> None:
    global _alarm_owners, _alarm_owners_synced_at
    with _alarm_cache_lock:
        if owner_username is None:
            _alarm_cache.clear()
            _alarm_cache_synced_at.clear()
            _alarm_owners = None
            _alarm_owners_synced_at = 0.0
        else:
            _alarm_cache.pop(owner_username, None)
            _alarm_cache_synced_at.pop(owner_username, None)
            if _alarm_owners is not None and owner_username not in _alarm_owners:
                _alarm_owners.append(owner_username)
                _alarm_owners_synced_at = time.monotonic()


def forget_alarm_owner(owner_username: str) -> None:
    global _alarm_owners
    invalidate_alarm_cache(owner_username)
    with _alarm_cache_lock:
        if _alarm_owners is not None:
            _alarm_owners = [owner for owner in _alarm_owners if owner != owner_username]

def _apply_fired_alarm_updates(owner_username: str, updates: list[tuple[str, tuple]]) -> None:
    if not updates or not db_write_many(updates):
        return
    fired_ids = {params[0] for _, params in updates}
    with _alarm_cache_lock:
        if owner_username not in _alarm_cache:
            return
        for alarm in _alarm_cache[owner_username]:
            if alarm.get("id") in fired_ids:
                alarm["status"] = "triggered"
                if alarm.get("repeat", "once") in ("once", ""):
                    alarm["active"] = 0
        _alarm_cache[owner_username][:] = [
            alarm for alarm in _alarm_cache[owner_username] if alarm.get("active", 1)
        ]

def alarm_scheduler_tick(now_time: str | None = None, cache_now: float | None = None,
                         owner_username: str | None = None) -> None:
    current_time = now_time or datetime.datetime.now().strftime("%H:%M")
    if owner_username is None:
        owner_names = refresh_alarm_owners()
    else:
        owner_names = [owner_username]
    for owner in owner_names:
        updates = []
        for alarm in refresh_alarm_cache(owner, now=cache_now):
            if alarm.get("time") != current_time:
                continue
            alarm_id = alarm.get("id")
            label = alarm.get("label", "Reminder")
            repeat = alarm.get("repeat", "once")
            message = groq_as_manager("alarm_fire", f"Alarm: {label}", max_tokens=60)
            send_os_notification(
                "J.A.R.V.I.S Reminder", message, timeout=15, owner_username=owner
            )
            push_system_event("alarm", message, {"label": label, "repeat": repeat}, owner)
            if repeat in ("once", ""):
                updates.append((
                    "UPDATE alarms SET active=0, status='triggered' WHERE id=? AND owner_username=?",
                    (alarm_id, owner),
                ))
            else:
                updates.append((
                    "UPDATE alarms SET status='triggered' WHERE id=? AND owner_username=?",
                    (alarm_id, owner),
                ))
        _apply_fired_alarm_updates(owner, updates)


def push_system_event(event_type: str, message: str, data: dict | None = None,
                      owner_username: str = "") -> None:
    with neural_lock:
        event = {
            "owner_username": owner_username, "type": event_type,
            "msg": message, "data": data or {}, "ts": ts(),
        }
        neural_state["event_queue"].append(event)
        neural_state["event_queue"] = neural_state["event_queue"][-50:]


def heartbeat_scan(owner_username: str | None = None) -> None:
    if owner_username is None:
        with heartbeat_lock:
            owners = list(_heartbeat_states)
        for owner in owners:
            heartbeat_scan(owner)
        return
    register_heartbeat_owner(owner_username)
    try:
        with heartbeat_lock:
            state = _heartbeat_states[owner_username]
            session = state["session"]
            session_mins = (time.time() - session["start"]) / 60
            already_reminded = session.get("break_reminded", False)
            last_remind = session.get("last_break_remind", 0)
            config = state["config"]
        break_mins = config.get("coding_break_mins", 90)
        message = ""
        if (session_mins > break_mins and not already_reminded
                and time.time() - last_remind > 3600):
            message = f"You have been working for {int(session_mins)} minutes. Consider taking a short break."
            with heartbeat_lock:
                session["break_reminded"] = True
                session["last_break_remind"] = time.time()
        if message:
            with heartbeat_lock:
                queue = _heartbeat_queues[owner_username]
                queue.append({
                    "owner_username": owner_username,
                    "msg": message,
                    "type": "heartbeat",
                    "ts": ts(),
                })
                del queue[:-20]
            send_os_notification(
                "J.A.R.V.I.S Heartbeat", message, timeout=6,
                owner_username=owner_username,
            )
        with heartbeat_lock:
            _heartbeat_states[owner_username]["config"]["last_run"] = time.time()
    except Exception as exc:
        log.error("heartbeat_scan: %s", exc)


def _heartbeat_thread() -> None:
    while True:
        try:
            with heartbeat_lock:
                owners = [
                    owner for owner, state in _heartbeat_states.items()
                    if state["config"].get("enabled")
                    and time.time() > state["config"].get("silence_until", 0)
                    and time.time() - state["config"].get("last_run", 0)
                    >= state["config"].get("interval", 30) * 60
                ]
            for owner in owners:
                heartbeat_scan(owner)
        except Exception as exc:
            log.error("heartbeat_thread: %s", exc)
        time.sleep(60)


def _reminder_scheduler() -> None:
    refresh_all_alarm_caches()
    while True:
        try:
            alarm_scheduler_tick()
        except Exception as exc:
            log.error("reminder_scheduler: %s", exc)
        time.sleep(60)


def start_background_threads() -> None:
    threading.Thread(target=_heartbeat_thread, daemon=True, name="HeartbeatEngine").start()
    threading.Thread(target=_reminder_scheduler, daemon=True, name="ReminderScheduler").start()
