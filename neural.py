"""
╔══════════════════════════════════════════════════════════════════╗
║  J.A.R.V.I.S v17.M — Neural Mode & Heartbeat Engine            ║
║  FIXED:                                                          ║
║    BUG-2  Alarm time format ("%Y-%m-%d %H:%M" → "%H:%M")       ║
║    BUG-3  Double queue push eliminated                           ║
║           heartbeat_scan  → heartbeat_queue ONLY                ║
║           reminder_scheduler → push_system_event ONLY           ║
║    BUG-R  repeat alarms (daily/weekly) stay active after fire   ║
╚══════════════════════════════════════════════════════════════════╝
"""
import datetime
import logging
import threading
import time
from threading import Lock

import psutil

from config import (
    heartbeat_cfg, heartbeat_queue, heartbeat_lock,
    work_session, work_session_lock,
)
from database import db_read, db_write, db_write_many, ts
from notifications import send_os_notification
from ai_engine import groq_as_manager

log = logging.getLogger("jarvis.neural")

# ── Neural state ─────────────────────────────────────────────────
neural_lock  = Lock()
neural_state = {
    "active":      False,
    "mode":        "normal",
    "conv_state":  "idle",
    "last_cmd":    "",
    "last_reply":  "",
    "alerts":      [],
    "event_queue": [],
}


def push_system_event(event_type: str, msg: str, data: dict = None):
    """Push proactive event into neural_state event_queue only."""
    with neural_lock:
        ev = {"type": event_type, "msg": msg, "data": data or {}, "ts": ts()}
        neural_state["event_queue"].append(ev)
        if len(neural_state["event_queue"]) > 50:
            neural_state["event_queue"] = neural_state["event_queue"][-50:]


# ── System event monitor ──────────────────────────────────────────
def system_event_monitor():
    prev = {"charging": None, "bat": 100}
    while True:
        try:
            bat = psutil.sensors_battery()
            if bat:
                if prev["charging"] is None:
                    prev["charging"] = bat.power_plugged
                    prev["bat"]      = bat.percent

                if bat.power_plugged != prev["charging"]:
                    if bat.power_plugged:
                        raw = f"Charger connected at {round(bat.percent)}% battery."
                        ev  = "charger_connected"
                    else:
                        raw = f"Charger disconnected at {round(bat.percent)}% battery."
                        ev  = "charger_disconnected"
                    msg = groq_as_manager(ev, raw, max_tokens=60)
                    push_system_event("charger", msg)
                    send_os_notification("J.A.R.V.I.S", msg)
                    prev["charging"] = bat.power_plugged

                if (
                    bat.percent <= heartbeat_cfg["battery_low"]
                    and not bat.power_plugged
                    and prev["bat"] > heartbeat_cfg["battery_low"]
                ):
                    raw = f"Battery critical at {round(bat.percent)}%."
                    msg = groq_as_manager("battery_low", raw, max_tokens=60)
                    push_system_event("battery_low", msg)
                    send_os_notification("J.A.R.V.I.S", msg)

                prev["bat"] = bat.percent
        except Exception as e:
            log.error("sys_event_monitor: %s", e)
        time.sleep(30)


# ── Heartbeat engine ──────────────────────────────────────────────
def _cleanup_heartbeat_queue():
    with heartbeat_lock:
        while len(heartbeat_queue) > 20:
            heartbeat_queue.pop(0)


def heartbeat_scan():
    """
    Check system health and push proactive messages.
    ✅ BUG-3 FIX: pushes to heartbeat_queue ONLY.
    push_system_event removed here to prevent double-voice delivery.
    Frontend polls /api/heartbeat/poll for heartbeat messages.
    """
    try:
        cpu  = psutil.cpu_percent(interval=1)
        vm   = psutil.virtual_memory()
        bat  = psutil.sensors_battery()
        msgs = []

        if cpu > heartbeat_cfg.get("cpu_threshold", 85):
            msgs.append(f"CPU is at {round(cpu)}%")
        if vm.percent > heartbeat_cfg.get("ram_threshold", 88):
            msgs.append(f"RAM usage is at {round(vm.percent)}%")
        if bat and not bat.power_plugged and bat.percent < heartbeat_cfg.get("battery_low", 15):
            msgs.append(f"Battery is at {round(bat.percent)}%")

        with work_session_lock:
            session_mins     = (time.time() - work_session["start"]) / 60
            already_reminded = work_session.get("break_reminded", False)
            last_remind      = work_session.get("last_break_remind", 0)

        break_mins = heartbeat_cfg.get("coding_break_mins", 90)
        if (
            session_mins > break_mins
            and not already_reminded
            and time.time() - last_remind > 3600
        ):
            msgs.append(f"You've been working for {int(session_mins)} minutes — take a short break")
            with work_session_lock:
                work_session["break_reminded"]    = True
                work_session["last_break_remind"] = time.time()

        if msgs:
            raw      = " | ".join(msgs)
            narrated = groq_as_manager("heartbeat", raw, max_tokens=80, context="auto")

            # ✅ BUG-3 FIX: heartbeat_queue ONLY — no push_system_event here
            with heartbeat_lock:
                heartbeat_queue.append({"msg": narrated, "type": "heartbeat", "ts": ts()})
            _cleanup_heartbeat_queue()
            send_os_notification("J.A.R.V.I.S Heartbeat", narrated, timeout=6)

        heartbeat_cfg["last_run"] = time.time()

    except Exception as e:
        log.error("heartbeat_scan: %s", e)


def _heartbeat_thread():
    while True:
        try:
            if (
                heartbeat_cfg.get("enabled")
                and time.time() > heartbeat_cfg.get("silence_until", 0)
            ):
                interval_secs = heartbeat_cfg.get("interval", 30) * 60
                last_run      = heartbeat_cfg.get("last_run", 0)
                if time.time() - last_run >= interval_secs:
                    heartbeat_scan()
        except Exception as e:
            log.error("heartbeat_thread: %s", e)
        time.sleep(60)


# ── Reminder / alarm scheduler ────────────────────────────────────
def _reminder_scheduler():
    """
    Poll alarms table every minute and fire due alarms.
    ✅ BUG-2 FIX: Compare HH:MM ONLY (not full datetime string).
    ✅ BUG-3 FIX: push_system_event ONLY — no heartbeat_queue append.
    ✅ BUG-R FIX: daily/weekly alarms stay active after firing.
    """
    while True:
        try:
            # ✅ BUG-2 FIX: use "%H:%M" — matches "15:30" stored in DB
            now_time = datetime.datetime.now().strftime("%H:%M")
            alarms   = db_read(
                "SELECT * FROM alarms WHERE active=1 AND time=?",
                (now_time,),
            )

            updates = []
            for alarm in alarms:
                alarm_id = alarm.get("id")
                label    = alarm.get("label", "Reminder")
                repeat   = alarm.get("repeat", "once")

                raw = f"Alarm: {label}"
                msg = groq_as_manager("alarm_fire", raw, max_tokens=60)
                send_os_notification("J.A.R.V.I.S Reminder", msg, timeout=15)

                # ✅ BUG-3 FIX: push to event_queue ONLY — no heartbeat_queue append
                push_system_event("alarm", msg, {"label": label, "repeat": repeat})

                # ✅ BUG-R FIX: only deactivate one-time alarms
                if repeat in ("once", ""):
                    updates.append((
                        "UPDATE alarms SET active=0, status='triggered' WHERE id=?",
                        (alarm_id,),
                    ))
                else:
                    # daily/weekly stay active — just mark triggered
                    updates.append((
                        "UPDATE alarms SET status='triggered' WHERE id=?",
                        (alarm_id,),
                    ))

            if updates:
                db_write_many(updates)

        except Exception as e:
            log.error("reminder_scheduler: %s", e)

        time.sleep(60)


def start_background_threads():
    threading.Thread(target=system_event_monitor, daemon=True, name="SysEventMon").start()
    threading.Thread(target=_heartbeat_thread,    daemon=True, name="HeartbeatEngine").start()
    threading.Thread(target=_reminder_scheduler,  daemon=True, name="ReminderScheduler").start()
    print("[NEURAL] ✅ Background threads started (SysEventMon, HeartbeatEngine, ReminderScheduler)")
