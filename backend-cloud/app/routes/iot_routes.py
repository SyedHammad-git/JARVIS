"""
J.A.R.V.I.S v17.M — IoT Routes Blueprint
FIXED: C2 monitor_add uses config JSON, C3 monitor_status reads from JSON config
"""
import json, logging
from flask import Blueprint, jsonify, request, Response
from database import db_read, db_write, ts
from auth import add_alert
from smarthome import (
    smarthome_devices, TUYA_DEVICES,
    toggle_device, save_devices, save_tuya_devices
)
from monitor import (
    cameras, cam_id_counter, cam_lock,
    motion_cfg, monitor_engine_running,
    _gen_frames, get_monitor_cache, invalidate_monitor_cache,
)
from error_utils import api_errors
from config import EXECUTION_MODE

log = logging.getLogger("jarvis.routes.iot")
iot = Blueprint("iot", __name__)


# ── Smart Home ────────────────────────────────────────────────────
@iot.route("/api/smarthome/devices", methods=["GET"])
@api_errors
def smarthome_get_devices():
    return jsonify({
        "devices": smarthome_devices,
        "count":   len(smarthome_devices),
        "on":      sum(1 for d in smarthome_devices.values() if d.get("state")),
    })

@iot.route("/api/smarthome/toggle/<device_id>", methods=["POST","OPTIONS"])
@api_errors
def smarthome_toggle(device_id):
    if request.method == "OPTIONS": return "", 204
    body        = request.get_json(silent=True) or {}
    force_state = body.get("state")
    updated     = toggle_device(device_id, force_state=force_state)
    if updated is None:
        return jsonify({"error":f"Device '{device_id}' not found"}), 404
    return jsonify({"ok": True, "device": updated})

@iot.route("/api/smarthome/all", methods=["POST","OPTIONS"])
@api_errors
def smarthome_all():
    if request.method == "OPTIONS": return "", 204
    state = bool((request.get_json(silent=True) or {}).get("state", False))
    for dev_id in smarthome_devices:
        toggle_device(dev_id, force_state=state)
    add_alert(f"SmartHome: All {'ON' if state else 'OFF'}")
    return jsonify({"ok": True, "state": state, "devices": smarthome_devices})

@iot.route("/api/smarthome/add", methods=["POST","OPTIONS"])
@api_errors
def smarthome_add():
    if request.method == "OPTIONS": return "", 204
    body  = request.get_json(silent=True) or {}
    name  = (body.get("name") or "").strip()
    dtype = (body.get("type") or "switch").strip()
    if not name: return jsonify({"error":"No name provided"}), 400
    dev_id = f"{dtype}_{len(smarthome_devices)+1}"
    smarthome_devices[dev_id] = {
        "name": name, "state": False, "type": dtype,
        "icon": body.get("icon","🔌"), "room": body.get("room",""),
    }
    save_devices()
    return jsonify({"ok": True, "device_id": dev_id, "device": smarthome_devices[dev_id]})

@iot.route("/api/smarthome/remove/<device_id>", methods=["POST","OPTIONS"])
@api_errors
def smarthome_remove(device_id):
    if request.method == "OPTIONS": return "", 204
    if device_id not in smarthome_devices:
        return jsonify({"error":"Device not found"}), 404
    removed = smarthome_devices.pop(device_id)
    save_devices()
    return jsonify({"ok": True, "removed": removed})

@iot.route("/api/smarthome/tuya/config", methods=["POST","OPTIONS"])
@api_errors
def smarthome_tuya_config():
    if request.method == "OPTIONS": return "", 204
    body = request.get_json(silent=True) or {}
    dev_id = body.get("device_id","")
    if not dev_id: return jsonify({"error":"device_id required"}), 400
    TUYA_DEVICES[dev_id] = {
        "device_id":  body.get("tuya_id",""),
        "device_key": body.get("tuya_key",""),
        "ip":         body.get("ip",""),
    }
    save_tuya_devices()
    return jsonify({"ok": True, "tuya_device_id": dev_id})


# ── Motion config ─────────────────────────────────────────────────
@iot.route("/api/motion/config", methods=["GET","POST","OPTIONS"])
@api_errors
def motion_config():
    if request.method == "OPTIONS": return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        for k in ("enabled","threshold","cooldown"):
            if k in body: motion_cfg[k] = body[k]
        return jsonify({"ok": True, "config": motion_cfg})
    return jsonify(motion_cfg)


# ── Camera streams ────────────────────────────────────────────────
@iot.route("/video_feed/<int:cam_id>")
@api_errors
def video_feed(cam_id):
    if EXECUTION_MODE != "local":
        return jsonify({"ok": False, "error": "local_camera_disabled"}), 403
    return Response(_gen_frames(cam_id),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@iot.route("/api/camera/list", methods=["GET"])
@api_errors
def camera_list():
    with cam_lock:
        safe = {k: {kk: vv for kk, vv in v.items() if kk != "cap"}
                for k, v in cameras.items()}
    return jsonify({"cameras": safe, "count": len(cameras)})

@iot.route("/api/camera/toggle/<int:cam_id>", methods=["POST","OPTIONS"])
@api_errors
def camera_toggle(cam_id):
    if request.method == "OPTIONS": return "", 204
    with cam_lock:
        cam = cameras.get(cam_id)
        if not cam: return jsonify({"error":"Camera not found"}), 404
        cam["active"] = not cam["active"]
        if not cam["active"] and cam.get("cap"):
            try: cam["cap"].release()
            except Exception: pass
            cam["cap"] = None
    return jsonify({"ok": True, "active": cameras[cam_id]["active"]})

@iot.route("/api/camera/add", methods=["POST","OPTIONS"])
@api_errors
def camera_add():
    if request.method == "OPTIONS": return "", 204
    body   = request.get_json(silent=True) or {}
    source = body.get("source", 0)
    with cam_lock:
        cam_id_counter[0] += 1
        cid  = cam_id_counter[0]
        name = (body.get("name") or f"Camera {cid}").strip()
        cameras[cid] = {"name": name, "source": source, "active": False, "cap": None}
    db_write("INSERT OR REPLACE INTO cameras(id,name,source,active) VALUES(?,?,?,0)",
             (cid, name, str(source)))
    return jsonify({"ok": True, "cam_id": cid, "name": name})

@iot.route("/api/camera/source", methods=["POST","OPTIONS"])
@api_errors
def camera_source():
    if request.method == "OPTIONS": return "", 204
    body   = request.get_json(silent=True) or {}
    cam_id = int(body.get("cam_id",0))
    source = body.get("source",0)
    with cam_lock:
        cam = cameras.get(cam_id)
        if not cam: return jsonify({"error":"Camera not found"}), 404
        if cam.get("cap"):
            try: cam["cap"].release()
            except Exception: pass
        cam.update({"source": source, "cap": None, "active": False})
    return jsonify({"ok": True, "cam_id": cam_id, "source": source})

@iot.route("/api/camera/remove/<int:cam_id>", methods=["POST","OPTIONS"])
@api_errors
def camera_remove(cam_id):
    if request.method == "OPTIONS": return "", 204
    with cam_lock:
        cam = cameras.pop(cam_id, None)
        if cam and cam.get("cap"):
            try: cam["cap"].release()
            except Exception: pass
    db_write("DELETE FROM cameras WHERE id=?", (cam_id,))
    return jsonify({"ok": True, "removed": cam_id})


# ── Uptime Monitor ────────────────────────────────────────────────
@iot.route("/api/monitor/list", methods=["GET"])
@api_errors
def monitor_list():
    rows = get_monitor_cache()
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
    # ✅ FIX C2: store url/timeout in config JSON column, not as separate columns
    cfg_json = json.dumps({"url": url, "timeout": timeout})
    added = db_write(
        "INSERT INTO monitors(name,type,config,status,created_at,active) VALUES(?,?,?,'running',?,1)",
        (name, typ, cfg_json, ts())
    )
    if added:
        invalidate_monitor_cache()
    return jsonify({"ok": True, "message":f"Monitor added: {name}"})

@iot.route("/api/monitor/pause", methods=["POST","OPTIONS"])
@api_errors
def monitor_pause():
    if request.method == "OPTIONS": return "", 204
    body   = request.get_json(silent=True) or {}
    mon_id = body.get("id")
    paused = bool(body.get("paused", True))
    if mon_id is None: return jsonify({"error":"No id"}), 400
    updated = db_write("UPDATE monitors SET status=? WHERE id=?",
                       ("paused" if paused else "running", mon_id))
    if updated:
        invalidate_monitor_cache()
    return jsonify({"ok": True, "paused": paused})

@iot.route("/api/monitor/delete", methods=["POST","OPTIONS"])
@api_errors
def monitor_delete():
    if request.method == "OPTIONS": return "", 204
    mon_id = (request.get_json(silent=True) or {}).get("id")
    if mon_id is None: return jsonify({"error":"No id"}), 400
    updated = db_write("UPDATE monitors SET active=0 WHERE id=?", (mon_id,))
    if updated:
        invalidate_monitor_cache()
    return jsonify({"ok": True})

@iot.route("/api/monitor/log", methods=["GET"])
@api_errors
def monitor_log():
    mon_id = request.args.get("id")
    limit  = min(int(request.args.get("limit",100)), 500)
    if mon_id:
        rows = db_read("SELECT * FROM monitor_log WHERE monitor_id=? ORDER BY id DESC LIMIT ?",
                       (mon_id, limit))
    else:
        rows = db_read("SELECT * FROM monitor_log ORDER BY id DESC LIMIT ?", (limit,))
    return jsonify({"log": rows, "count": len(rows)})

@iot.route("/api/monitor/status", methods=["GET"])
@api_errors
def monitor_status():
    """✅ FIX C3: parse url/timeout from config JSON, don't select non-existent columns."""
    rows = [monitor for monitor in get_monitor_cache() if monitor.get("active", 1)]
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
