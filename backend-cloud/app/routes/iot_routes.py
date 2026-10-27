"""
J.A.R.V.I.S v17.M — IoT Routes Blueprint
FIXED: C2 monitor_add uses config JSON, C3 monitor_status reads from JSON config
"""
import json, logging
from flask import Blueprint, g, jsonify, request
from app.db import db_read, db_write, ts
from app.auth import add_alert
from app.smarthome import (
    get_devices, add_device, remove_device, toggle_device,
)
from app.monitor import (
    monitor_engine_running, get_monitor_cache, invalidate_monitor_cache,
)
from app.error_utils import api_errors

log = logging.getLogger("jarvis.routes.iot")
iot = Blueprint("iot", __name__)


# ── Smart Home ────────────────────────────────────────────────────
@iot.route("/api/smarthome/devices", methods=["GET"])
@api_errors
def smarthome_get_devices():
    owner = g.current_user["username"]
    devices = get_devices(owner)
    return jsonify({
        "devices": devices,
        "count":   len(devices),
        "on":      sum(1 for d in devices.values() if d.get("state")),
    })

@iot.route("/api/smarthome/toggle/<device_id>", methods=["POST","OPTIONS"])
@api_errors
def smarthome_toggle(device_id):
    if request.method == "OPTIONS": return "", 204
    body        = request.get_json(silent=True) or {}
    force_state = body.get("state")
    updated     = toggle_device(
        device_id, force_state=force_state, owner_username=g.current_user["username"]
    )
    if updated is None:
        return jsonify({"error":f"Device '{device_id}' not found"}), 404
    return jsonify({"ok": True, "device": updated})

@iot.route("/api/smarthome/all", methods=["POST","OPTIONS"])
@api_errors
def smarthome_all():
    if request.method == "OPTIONS": return "", 204
    state = bool((request.get_json(silent=True) or {}).get("state", False))
    owner = g.current_user["username"]
    devices = get_devices(owner)
    for dev_id in devices:
        toggle_device(dev_id, force_state=state, owner_username=owner)
    add_alert(
        f"SmartHome: All {'ON' if state else 'OFF'}",
        owner_username=g.current_user["username"],
    )
    return jsonify({"ok": True, "state": state, "devices": get_devices(owner)})

@iot.route("/api/smarthome/add", methods=["POST","OPTIONS"])
@api_errors
def smarthome_add():
    if request.method == "OPTIONS": return "", 204
    body  = request.get_json(silent=True) or {}
    name  = (body.get("name") or "").strip()
    dtype = (body.get("type") or "switch").strip()
    if not name: return jsonify({"error":"No name provided"}), 400
    owner = g.current_user["username"]
    devices = get_devices(owner)
    dev_id = f"{dtype}_{len(devices)+1}"
    device = {
        "name": name, "state": False, "type": dtype,
        "icon": body.get("icon","🔌"), "room": body.get("room",""),
    }
    add_device(owner, dev_id, device)
    return jsonify({"ok": True, "device_id": dev_id, "device": device})

@iot.route("/api/smarthome/remove/<device_id>", methods=["POST","OPTIONS"])
@api_errors
def smarthome_remove(device_id):
    if request.method == "OPTIONS": return "", 204
    removed = remove_device(g.current_user["username"], device_id)
    if removed is None:
        return jsonify({"error":"Device not found"}), 404
    return jsonify({"ok": True, "removed": removed})

# ── Uptime Monitor ────────────────────────────────────────────────
@iot.route("/api/monitor/list", methods=["GET"])
@api_errors
def monitor_list():
    rows = get_monitor_cache(g.current_user["username"])
    return jsonify({"monitors": rows, "count": len(rows), "engine": monitor_engine_running})

@iot.route("/api/monitor/add", methods=["POST","OPTIONS"])
@api_errors
def monitor_add():
    if request.method == "OPTIONS": return "", 204
    body    = request.get_json(silent=True) or {}
    url     = (body.get("url") or "").strip()
    name    = (body.get("name") or url).strip()
    typ     = body.get("type","http")
    timeout = int(body.get("timeout",10))
    if not url: return jsonify({"error":"No url provided"}), 400
    if typ not in ("http", "https"):
        return jsonify({"error":"Only HTTP and HTTPS monitors are supported"}), 400
    # ✅ FIX C2: store url/timeout in config JSON column, not as separate columns
    cfg_json = json.dumps({"url": url, "timeout": timeout})
    added = db_write(
        "INSERT INTO monitors(owner_username,name,type,config,status,created_at,active) "
        "VALUES(?,?,?,?,'running',?,1)",
        (g.current_user["username"], name, typ, cfg_json, ts())
    )
    if added:
        invalidate_monitor_cache(g.current_user["username"])
    return jsonify({"ok": True, "message":f"Monitor added: {name}"})

@iot.route("/api/monitor/pause", methods=["POST","OPTIONS"])
@api_errors
def monitor_pause():
    if request.method == "OPTIONS": return "", 204
    body   = request.get_json(silent=True) or {}
    mon_id = body.get("id")
    paused = bool(body.get("paused", True))
    if mon_id is None: return jsonify({"error":"No id"}), 400
    updated = db_write("UPDATE monitors SET status=? WHERE id=? AND owner_username=?",
                       ("paused" if paused else "running", mon_id, g.current_user["username"]))
    if updated:
        invalidate_monitor_cache(g.current_user["username"])
    return jsonify({"ok": True, "paused": paused})

@iot.route("/api/monitor/delete", methods=["POST","OPTIONS"])
@api_errors
def monitor_delete():
    if request.method == "OPTIONS": return "", 204
    mon_id = (request.get_json(silent=True) or {}).get("id")
    if mon_id is None: return jsonify({"error":"No id"}), 400
    updated = db_write("UPDATE monitors SET active=0 WHERE id=? AND owner_username=?",
                       (mon_id, g.current_user["username"]))
    if updated:
        invalidate_monitor_cache(g.current_user["username"])
    return jsonify({"ok": True})

@iot.route("/api/monitor/log", methods=["GET"])
@api_errors
def monitor_log():
    mon_id = request.args.get("id")
    limit  = min(int(request.args.get("limit",100)), 500)
    owner = g.current_user["username"]
    if mon_id:
        rows = db_read(
            "SELECT * FROM monitor_log WHERE owner_username=? AND monitor_id=? ORDER BY id DESC LIMIT ?",
            (owner, mon_id, limit),
        )
    else:
        rows = db_read(
            "SELECT * FROM monitor_log WHERE owner_username=? ORDER BY id DESC LIMIT ?",
            (owner, limit),
        )
    return jsonify({"log": rows, "count": len(rows)})

@iot.route("/api/monitor/status", methods=["GET"])
@api_errors
def monitor_status():
    """✅ FIX C3: parse url/timeout from config JSON, don't select non-existent columns."""
    rows = [
        monitor for monitor in get_monitor_cache(g.current_user["username"])
        if monitor.get("active", 1)
    ]
    result = []
    for r in rows:
        try:   cfg = json.loads(r.get("config","{}") or "{}")
        except Exception: cfg = {}
        result.append({
            "id":            r["id"],
            "name":          r["name"],
            "type":          r["type"],
            "url":           cfg.get("url",""),
            "timeout":       cfg.get("timeout",10),
            "status":        r["status"],
            "last_check":    r["last_check"],
            "trigger_count": r["trigger_count"],
        })
    up   = sum(1 for r in result if r["status"] == "up")
    down = sum(1 for r in result if r["status"] == "down")
    return jsonify({
        "monitors":       result,
        "engine_running": monitor_engine_running,
        "up_count":       up,
        "down_count":     down,
    })
