"""
J.A.R.V.I.S v17.M — Notifications
FIXED: C5 safe_msg/safe_title always defined before any use
"""
import datetime, json, logging, threading
from pathlib import Path

from app.config import discord_cfg, REQUESTS_OK, _req
from app.db import db_read, db_write, ts

log = logging.getLogger("jarvis.notifications")

def send_discord_alert(message: str, image_path: str = None) -> bool:
    if not REQUESTS_OK: return False
    url = discord_cfg.get("webhook_url", "").strip()
    if not url or not url.startswith("https://discord.com/api/webhooks/"): return False
    try:
        embed = {
            "title": "🤖 JARVIS ALERT",
            "description": message, "color": 0x00f0ff,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "footer": {"text": "J.A.R.V.I.S v17.M • Built by Hammad"}
        }
        payload = {"username": "J.A.R.V.I.S", "embeds": [embed]}
        if image_path and Path(image_path).exists():
            with open(image_path, "rb") as f:
                resp = _req.post(url, data={"payload_json": json.dumps(payload)},
                                 files={"file": (Path(image_path).name, f, "image/jpeg")}, timeout=10)
        else:
            resp = _req.post(url, json=payload, timeout=10)
        ok = resp.status_code in (200, 204)
        if ok:
            threading.Thread(
                target=db_write,
                args=("INSERT INTO events(type,message,created_at) VALUES(?,?,?)",
                      ("discord", message[:200], ts())),
                daemon=True
            ).start()
        return ok
    except Exception as e:
        log.error("Discord alert failed: %s", e)
        return False

def send_os_notification(
    title: str,
    message: str,
    timeout: int = 8,
    *,
    owner_username: str | None = None,
) -> bool:
    from app.devices.gateway import call_device, is_online

    client_timeout = max(1, min(int(timeout), 10))
    if owner_username:
        devices = db_read(
            "SELECT device_id, owner_username FROM devices "
            "WHERE revoked=0 AND owner_username=? ORDER BY created_at",
            (owner_username,),
        )
    else:
        devices = db_read(
            "SELECT device_id, owner_username FROM devices WHERE revoked=0 ORDER BY created_at"
        )
    for device in devices:
        device_id = device.get("device_id")
        owner = device.get("owner_username")
        if not device_id or not owner or not is_online(device_id):
            continue
        result = call_device(
            device_id,
            "notify",
            {"title": str(title)[:80], "body": str(message)[:300]},
            timeout=client_timeout,
            owner_username=owner,
        )
        if result.get("ok"):
            return True
    return False
