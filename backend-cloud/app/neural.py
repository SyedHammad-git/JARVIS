"""In-memory cached alarm scheduler and service-side heartbeat."""
from __future__ import annotations

import datetime
import logging
import threading
import time
from threading import Lock

from app.config import heartbeat_cfg, heartbeat_queue, heartbeat_lock, work_session, work_session_lock
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

_ALARM_CACHE_TTL = 30 * 60
_alarm_cache_lock = Lock()
_alarm_cache: list[dict] | None = None
_alarm_cache_synced_at = 0.0


def refresh_alarm_cache(force: bool = False, now: float | None = None) -> list[dict]:
    global _alarm_cache, _alarm_cache_synced_at
    instant = time.monotonic() if now is None else now
    with _alarm_cache_lock:
        if (_alarm_cache is not None and not force
                and instant - _alarm_cache_synced_at < _ALARM_CACHE_TTL):
            return [dict(alarm) for alarm in _alarm_cache]
        _alarm_cache = db_read("SELECT * FROM alarms WHERE active=1 ORDER BY time ASC")
        _alarm_cache_synced_at = instant
        return [dict(alarm) for alarm in _alarm_cache]


def invalidate_alarm_cache() -> None:
    global _alarm_cache, _alarm_cache_synced_at
    with _alarm_cache_lock:
        _alarm_cache = None
        _alarm_cache_synced_at = 0.0


def _apply_fired_alarm_updates(updates: list[tuple[str, tuple]]) -> None:
    if not updates or not db_write_many(updates):
        return
    fired_ids = {params[0] for _, params in updates}
    with _alarm_cache_lock:
        if _alarm_cache is None:
            return
        for alarm in _alarm_cache:
            if alarm.get("id") in fired_ids:
                alarm["status"] = "triggered"
                if alarm.get("repeat", "once") in ("once", ""):
                    alarm["active"] = 0
        _alarm_cache[:] = [alarm for alarm in _alarm_cache if alarm.get("active", 1)]


def alarm_scheduler_tick(now_time: str | None = None, cache_now: float | None = None) -> None:
    current_time = now_time or datetime.datetime.now().strftime("%H:%M")
    alarms = refresh_alarm_cache(now=cache_now)
    updates = []
    for alarm in alarms:
        if alarm.get("time") != current_time:
            continue
        alarm_id = alarm.get("id")
        label = alarm.get("label", "Reminder")
        repeat = alarm.get("repeat", "once")
        message = groq_as_manager("alarm_fire", f"Alarm: {label}", max_tokens=60)
        send_os_notification("J.A.R.V.I.S Reminder", message, timeout=15)
        push_system_event("alarm", message, {"label": label, "repeat": repeat})
        if repeat in ("once", ""):
            updates.append(("UPDATE alarms SET active=0, status='triggered' WHERE id=?", (alarm_id,)))
        else:
            updates.append(("UPDATE alarms SET status='triggered' WHERE id=?", (alarm_id,)))
    _apply_fired_alarm_updates(updates)


def push_system_event(event_type: str, message: str, data: dict | None = None) -> None:
    with neural_lock:
        event = {"type": event_type, "msg": message, "data": data or {}, "ts": ts()}
        neural_state["event_queue"].append(event)
        neural_state["event_queue"] = neural_state["event_queue"][-50:]


def _cleanup_heartbeat_queue() -> None:
    with heartbeat_lock:
        while len(heartbeat_queue) > 20:
            heartbeat_queue.pop(0)


def heartbeat_scan() -> None:
    try:
        with work_session_lock:
            session_mins = (time.time() - work_session["start"]) / 60
            already_reminded = work_session.get("break_reminded", False)
            last_remind = work_session.get("last_break_remind", 0)
        break_mins = heartbeat_cfg.get("coding_break_mins", 90)
        message = ""
        if (session_mins > break_mins and not already_reminded
                and time.time() - last_remind > 3600):
            message = f"You have been working for {int(session_mins)} minutes. Consider taking a short break."
            with work_session_lock:
                work_session["break_reminded"] = True
                work_session["last_break_remind"] = time.time()
        if message:
            with heartbeat_lock:
                heartbeat_queue.append({"msg": message, "type": "heartbeat", "ts": ts()})
            _cleanup_heartbeat_queue()
            send_os_notification("J.A.R.V.I.S Heartbeat", message, timeout=6)
        heartbeat_cfg["last_run"] = time.time()
    except Exception as exc:
        log.error("heartbeat_scan: %s", exc)


def _heartbeat_thread() -> None:
    while True:
        try:
            if (heartbeat_cfg.get("enabled")
                    and time.time() > heartbeat_cfg.get("silence_until", 0)):
                interval = heartbeat_cfg.get("interval", 30) * 60
                if time.time() - heartbeat_cfg.get("last_run", 0) >= interval:
                    heartbeat_scan()
        except Exception as exc:
            log.error("heartbeat_thread: %s", exc)
        time.sleep(60)


def _reminder_scheduler() -> None:
    refresh_alarm_cache()
    while True:
        try:
            alarm_scheduler_tick()
        except Exception as exc:
            log.error("reminder_scheduler: %s", exc)
        time.sleep(60)


def start_background_threads() -> None:
    threading.Thread(target=_heartbeat_thread, daemon=True, name="HeartbeatEngine").start()
    threading.Thread(target=_reminder_scheduler, daemon=True, name="ReminderScheduler").start()
