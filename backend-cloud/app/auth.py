"""Server-side alert and audit counters."""
from __future__ import annotations

import datetime
import threading

from app.config import cache, stat_lock
from app.db import db_write, ts


def add_alert(message: str, owner_username: str = "") -> None:
    with stat_lock:
        cache["alerts"].append({
            "msg": message,
            "ts": datetime.datetime.now().strftime("%H:%M:%S"),
            "owner_username": owner_username,
        })
        cache["alerts"] = cache["alerts"][-50:]
    threading.Thread(
        target=db_write,
        args=(
            "INSERT INTO events(owner_username,type,message,created_at) VALUES(?,?,?,?)",
            (owner_username, "alert", message[:300], ts()),
        ),
        daemon=True,
    ).start()
