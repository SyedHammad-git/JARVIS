"""Server-side alert and audit counters."""
from __future__ import annotations

import datetime
import threading

from app.config import cache, stat_lock
from app.db import db_write, ts


def add_alert(message: str) -> None:
    with stat_lock:
        cache["alerts"].append({
            "msg": message,
            "ts": datetime.datetime.now().strftime("%H:%M:%S"),
        })
        cache["alerts"] = cache["alerts"][-50:]
    threading.Thread(
        target=db_write,
        args=(
            "INSERT INTO events(type,message,created_at) VALUES(?,?,?)",
            ("alert", message[:300], ts()),
        ),
        daemon=True,
    ).start()
