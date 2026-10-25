"""
J.A.R.V.I.S v17.M — Notifications
FIXED: C5 safe_msg/safe_title always defined before any use
"""
import datetime, json, logging, subprocess, threading
from pathlib import Path

from app.config import discord_cfg, REQUESTS_OK, _req
from app.db import db_write, ts

log = logging.getLogger("jarvis.notifications")

try:
    from plyer import notification as _plyer_notif; PLYER_OK = True
except ImportError:
    _plyer_notif = None; PLYER_OK = False

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

def send_os_notification(title: str, message: str, timeout: int = 8) -> bool:
    msg_short  = message[:200]
    # ✅ FIX C5: Define safe vars BEFORE any try block that might use them
    safe_title = title.replace("'", "").replace('"', "")
    safe_msg   = msg_short.replace("'", "").replace('"', "")

    # Method 1: plyer
    if PLYER_OK:
        try:
            _plyer_notif.notify(title=title, message=msg_short,
                                app_name="J.A.R.V.I.S", timeout=timeout)
            return True
        except Exception:
            pass

    # Method 2: PowerShell toast (Windows 10/11)
    try:
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager,"
            "Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
            "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f"$t.SelectSingleNode('//text[@id=1]').InnerText='{safe_title}';"
            f"$t.SelectSingleNode('//text[@id=2]').InnerText='{safe_msg}';"
            "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
            "[Windows.UI.Notifications.ToastNotificationManager]"
            "::CreateToastNotifier('JARVIS').Show($n)"
        )
        subprocess.Popen(["powershell", "-Command", ps],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        pass

    # Method 3: msg command fallback
    try:
        subprocess.Popen(f'msg * /time:{timeout} "{safe_title}: {safe_msg}"',
                         shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        pass
    return False
