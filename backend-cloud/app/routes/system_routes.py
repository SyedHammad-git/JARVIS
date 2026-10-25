"""J.A.R.V.I.S v17.M — System Routes Blueprint"""
import hashlib, logging, subprocess, time
from pathlib import Path
try:
    import pyautogui; _PGUI_OK = True
except Exception:
    pyautogui = None; _PGUI_OK = False
from flask import Blueprint, jsonify, request
from config import (
    BLACKLIST, security_settings, cache,
    discord_cfg, heartbeat_cfg, heartbeat_queue, heartbeat_lock
)
from database import db_read, cfg_set, HOME
from auth import add_alert, verify_pin
from notifications import send_discord_alert
from tools import (
    tool_get_weather, tool_get_processes, tool_kill_process,
    tool_describe_screen, tool_file_read
)
from error_utils import api_errors, classify_exception

log    = logging.getLogger("jarvis.routes.system")
system = Blueprint("system", __name__)


# ── Heartbeat ─────────────────────────────────────────────────────
@system.route("/api/heartbeat/status", methods=["GET","POST","OPTIONS"])
@api_errors
def heartbeat_status():
    if request.method == "OPTIONS": return "", 204
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "enabled" in data: heartbeat_cfg["enabled"] = bool(data["enabled"])
        return jsonify({"ok": True, "config": heartbeat_cfg})
    with heartbeat_lock: pending = list(heartbeat_queue)
    return jsonify({
        "enabled":       heartbeat_cfg.get("enabled"),
        "interval_min":  heartbeat_cfg.get("interval",30),
        "last_run":      heartbeat_cfg.get("last_run",0),
        "silence_until": heartbeat_cfg.get("silence_until",0),
        "pending":       pending, "pending_count": len(pending),
    })

@system.route("/api/heartbeat/poll", methods=["GET"])
@api_errors
def heartbeat_poll():
    with heartbeat_lock: msgs = list(heartbeat_queue); heartbeat_queue.clear()
    return jsonify({"messages": msgs, "count": len(msgs)})

@system.route("/api/heartbeat/config", methods=["GET","POST","OPTIONS"])
@api_errors
def heartbeat_config():
    if request.method == "OPTIONS": return "", 204
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for k in ("enabled","interval","cpu_threshold","ram_threshold","battery_low","coding_break_mins"):
            if k in data: heartbeat_cfg[k] = data[k]
        return jsonify({"ok": True, "config": heartbeat_cfg})
    return jsonify(heartbeat_cfg)

@system.route("/api/heartbeat/log", methods=["GET"])
@api_errors
def heartbeat_log():
    rows = db_read("SELECT * FROM events WHERE type='heartbeat' ORDER BY id DESC LIMIT 50")
    return jsonify({"log": rows, "count": len(rows)})


# ── Discord ───────────────────────────────────────────────────────
@system.route("/api/discord/config", methods=["GET","POST","OPTIONS"])
@api_errors
def discord_config():
    if request.method == "OPTIONS": return "", 204
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "webhook_url" in data:
            discord_cfg["webhook_url"] = data["webhook_url"]
            cfg_set("discord_webhook_url", data["webhook_url"])
        if "enabled" in data:
            discord_cfg["enabled"] = bool(data["enabled"])
            cfg_set("discord_enabled","true" if data["enabled"] else "false")
        return jsonify({"ok": True})
    return jsonify({
        "webhook_configured": bool(discord_cfg.get("webhook_url","")),
        "enabled": discord_cfg.get("enabled")
    })

@system.route("/api/discord/test", methods=["POST","OPTIONS"])
@api_errors
def discord_test():
    if request.method == "OPTIONS": return "", 204
    ok = send_discord_alert("🤖 JARVIS Discord test — connection successful!")
    return jsonify({"ok": ok})

@system.route("/api/discord/send", methods=["POST","OPTIONS"])
@api_errors
def discord_send():
    if request.method == "OPTIONS": return "", 204
    msg = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not msg: return jsonify({"error": "No message"}), 400
    return jsonify({"ok": send_discord_alert(msg)})


# ── Process management ────────────────────────────────────────────
@system.route("/api/process/list", methods=["GET"])
@api_errors
def process_list():
    result = tool_get_processes(request.args.get("filter"))
    return jsonify({"processes": cache.get("processes",[]), "text": result})

@system.route("/api/process/kill", methods=["POST","OPTIONS"])
@api_errors
def process_kill():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    target = data.get("name") or data.get("pid") or ""
    if not target: return jsonify({"error": "No name or pid"}), 400
    return jsonify({"ok": True, "result": tool_kill_process(str(target))})


# ── File browser ──────────────────────────────────────────────────
@system.route("/api/files/list", methods=["GET"])
@api_errors
def files_list():
    path_str = request.args.get("path", str(HOME))
    try:
        p     = Path(path_str).resolve()
        items = []
        for f in sorted(p.iterdir()):
            try:
                items.append({
                    "name":     f.name,
                    "path":     str(f),
                    "is_dir":   f.is_dir(),
                    "size":     f.stat().st_size if f.is_file() else 0,
                    "modified": f.stat().st_mtime,
                })
            except PermissionError:
                pass
        return jsonify({"path": str(p), "items": items})
    except Exception as e:
        phrase, code = classify_exception(e)
        return jsonify({"error": f"{(phrase or 'an unexpected error occurred').capitalize()}, Sir.", "code": code}), code

@system.route("/api/files/read", methods=["GET"])
@api_errors
def files_read():
    fp = request.args.get("path","")
    if not fp: return jsonify({"error": "No path"}), 400
    return jsonify({"content": tool_file_read(fp)})


# ── Clipboard ─────────────────────────────────────────────────────
@system.route("/api/clipboard", methods=["GET","POST","OPTIONS"])
@api_errors
def clipboard():
    if request.method == "OPTIONS": return "", 204
    from tools import tool_get_clipboard, tool_set_clipboard
    if request.method == "POST":
        text = (request.get_json(silent=True) or {}).get("text","")
        return jsonify({"ok": True, "result": tool_set_clipboard(text)})
    return jsonify({"content": tool_get_clipboard()})


# ── Weather ───────────────────────────────────────────────────────
@system.route("/api/weather", methods=["GET"])
@api_errors
def weather():
    city = request.args.get("city","Faisalabad")
    return jsonify({"weather": tool_get_weather(city), "city": city})


# ── Security ──────────────────────────────────────────────────────
@system.route("/api/security/toggle", methods=["POST","OPTIONS"])
@api_errors
def security_toggle():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    key, val = data.get("key",""), data.get("value")
    if key in security_settings and val is not None:
        security_settings[key] = bool(val)
        return jsonify({"ok": True, "settings": security_settings})
    return jsonify({"error": "Invalid key"}), 400

@system.route("/api/security/blacklist/add", methods=["POST","OPTIONS"])
@api_errors
def blacklist_add():
    if request.method == "OPTIONS": return "", 204
    word = ((request.get_json(silent=True) or {}).get("word") or "").strip().lower()
    if word and word not in BLACKLIST:
        BLACKLIST.append(word)
        return jsonify({"ok": True, "blacklist": BLACKLIST})
    return jsonify({"ok": False, "reason": "Empty or duplicate"}), 400

@system.route("/api/security/blacklist", methods=["GET"])
@api_errors
def blacklist_get():
    return jsonify({"blacklist": BLACKLIST, "settings": security_settings})


# ── Login / PIN ───────────────────────────────────────────────────
@system.route("/api/login", methods=["POST","OPTIONS"])
@api_errors
def mobile_login():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    pin  = (data.get("pin") or "").strip()
    if verify_pin(pin):
        from flask import session
        session["jarvis_authed"] = True
        token = hashlib.sha256(
            f"jarvis-{pin}-{int(time.time()//3600)}".encode()
        ).hexdigest()[:32]
        add_alert("Mobile login: success")
        return jsonify({"status":"success","token":token})
    add_alert("Mobile login: FAILED — wrong PIN")
    return jsonify({"status":"error","message":"Invalid PIN"}), 401

@system.route("/api/pin/change", methods=["POST","OPTIONS"])
@api_errors
def pin_change():
    if request.method == "OPTIONS": return "", 204
    data    = request.get_json(silent=True) or {}
    old_pin = (data.get("old_pin") or "").strip()
    new_pin = (data.get("new_pin") or "").strip()
    if not verify_pin(old_pin):
        return jsonify({"error":"Current PIN incorrect"}), 401
    if not new_pin.isdigit() or len(new_pin) < 4:
        return jsonify({"error":"New PIN must be ≥4 digits"}), 400
    cfg_set("pin", new_pin)
    add_alert("PIN changed")
    return jsonify({"ok":True,"message":"PIN updated, Sir."})


# ── System power actions ──────────────────────────────────────────
@system.route("/api/system/<action>", methods=["POST","OPTIONS"])
@api_errors
def system_action(action):
    if request.method == "OPTIONS": return "", 204
    ACTIONS = {
        "shutdown":"shutdown /s /t 10","restart":"shutdown /r /t 10",
        "sleep":"rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "lock":"rundll32.exe user32.dll,LockWorkStation","hibernate":"shutdown /h",
    }
    cmd = ACTIONS.get(action)
    if not cmd: return jsonify({"error":f"Unknown action: {action}"}), 400
    add_alert(f"System: {action}")
    subprocess.Popen(cmd, shell=True)
    return jsonify({"ok":True,"action":action})


# ── Media controls ────────────────────────────────────────────────
@system.route("/api/media/<action>", methods=["POST","OPTIONS"])
@api_errors
def media_action(action):
    if request.method == "OPTIONS": return "", 204
    KEY_MAP = {
        "play":"playpause","pause":"playpause","playpause":"playpause",
        "next":"nexttrack","prev":"prevtrack","previous":"prevtrack","stop":"stop",
        "volumeup":"volumeup","volumedown":"volumedown","mute":"volumemute",
    }
    key = KEY_MAP.get(action.lower())
    if not key: return jsonify({"error":f"Unknown media action: {action}"}), 400
    if not _PGUI_OK: return jsonify({"error":"pyautogui unavailable"}), 503
    try:
        pyautogui.press(key)
        return jsonify({"ok":True,"action":action})
    except Exception as e:
        phrase, code = classify_exception(e)
        return jsonify({"error": f"{(phrase or 'an unexpected error occurred').capitalize()}, Sir.", "code": code}), code


# ── Screen ────────────────────────────────────────────────────────
@system.route("/api/screen/analyze", methods=["POST","OPTIONS"])
@api_errors
def screen_analyze():
    if request.method == "OPTIONS": return "", 204
    return jsonify({"ok":True,"description":tool_describe_screen()})

@system.route("/api/screen/active_window", methods=["GET"])
@api_errors
def screen_active_window():
    from monitor import get_active_window
    win = get_active_window()
    return jsonify({
        "window": win,
        "app":    win.split(" - ")[-1] if " - " in win else win,
        "cached": cache.get("active_window",""),
    })
