"""HTTP routes for pairing and device status. Pairing requires a PIN session."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, g, jsonify, request

from app.config import DEVICE_ID, EXECUTION_MODE
from app.devices.gateway import is_online
from app.devices.pairing import (
    get_device,
    get_device_status_cached,
    create_pair_code,
    issue_device,
    list_devices,
    revoke_device,
    redeem_pair_code,
    set_device_scopes,
)
from app.error_utils import api_errors

log = logging.getLogger("jarvis.devices")

devices_bp = Blueprint("devices", __name__)
_pair_attempt_lock = threading.Lock()
_pair_attempts: dict[str, deque[float]] = defaultdict(deque)
_PAIR_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


@devices_bp.route("/api/devices/pair", methods=["POST", "OPTIONS"])
@api_errors
def pair_device():
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "PC").strip() or "PC"
    device_id, token = issue_device(name, g.current_user["username"])
    # Token returned ONCE. It is not logged and will not appear in GET /api/devices.
    return jsonify({
        "ok": True,
        "device_id": device_id,
        "token": token,
        "name": name,
        "once": True,
        "message": "Save this token now — it will not be shown again.",
    })


@devices_bp.route("/api/devices/pair-code", methods=["POST", "OPTIONS"])
@api_errors
def create_device_pair_code():
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    name = body.get("name", "PC")
    if not isinstance(name, str) or len(name.strip()) > 64:
        return jsonify({"ok": False, "error": "invalid_device_name"}), 400
    code, expires_at = create_pair_code(g.current_user["username"], name.strip() or "PC")
    return jsonify({
        "ok": True,
        "code": code,
        "expires_at": expires_at,
        "expires_in": 600,
    })


@devices_bp.route("/pairing/redeem-code", methods=["POST", "OPTIONS"])
@api_errors
def redeem_device_pair_code():
    if request.method == "OPTIONS":
        return "", 204
    client_ip = request.remote_addr or "unknown"
    now = time.monotonic()
    with _pair_attempt_lock:
        attempts = _pair_attempts[client_ip]
        while attempts and now - attempts[0] >= 300:
            attempts.popleft()
        if len(attempts) >= 10:
            return jsonify({"ok": False, "error": "pair_code_rate_limited"}), 429
        attempts.append(now)

    body = request.get_json(silent=True) or {}
    code = body.get("code")
    if not isinstance(code, str):
        return jsonify({"ok": False, "error": "invalid_pair_code"}), 400
    code = code.strip().upper()
    if not _PAIR_CODE_RE.fullmatch(code):
        return jsonify({"ok": False, "error": "invalid_pair_code"}), 400
    result = redeem_pair_code(code)
    if not result:
        return jsonify({"ok": False, "error": "pair_code_expired_or_invalid"}), 404
    device_id, token, name = result
    return jsonify({
        "ok": True,
        "device_id": device_id,
        "token": token,
        "name": name,
        "once": True,
    })


@devices_bp.route("/api/devices", methods=["GET"])
@api_errors
def devices_list():
    rows = list_devices(g.current_user["username"])
    for r in rows:
        r["online"] = is_online(r["device_id"])
    return jsonify({"ok": True, "devices": rows, "count": len(rows)})


@devices_bp.route("/api/devices/<device_id>/revoke", methods=["POST", "OPTIONS"])
@api_errors
def devices_revoke(device_id):
    if request.method == "OPTIONS":
        return "", 204
    device = get_device(device_id)
    if not device or device.get("owner_username") != g.current_user["username"]:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not revoke_device(device_id):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "device_id": device_id, "revoked": True})


@devices_bp.route("/api/device/status", methods=["GET"])
@api_errors
def device_status():
    device_id = (request.args.get("device_id") or DEVICE_ID or "").strip()
    device = get_device_status_cached(device_id)
    if hasattr(g, "device_status"):
        if g.device_status.get("device_id") != device_id:
            return jsonify({"ok": False, "error": "not_found"}), 404
    else:
        full_device = get_device(device_id)
        if not device or not full_device or full_device.get("owner_username") != g.current_user["username"]:
            return jsonify({"ok": False, "error": "not_found"}), 404
    online = is_online(device_id) if EXECUTION_MODE == "remote" else True
    if EXECUTION_MODE == "local":
        label = "local"
    else:
        label = "online" if online else "offline"
    return jsonify({
        "ok": True,
        "device_id": device_id,
        "execution_mode": EXECUTION_MODE,
        "online": bool(online),
        "revoked": bool(device and int(device.get("revoked") or 0)),
        "label": label,
    })


@devices_bp.route("/api/devices/<device_id>/scopes", methods=["PUT", "OPTIONS"])
@api_errors
def device_scopes(device_id):
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    scopes = body.get("scopes")
    if not set_device_scopes(device_id, g.current_user["username"], scopes):
        return jsonify({"ok": False, "error": "invalid_scopes_or_not_found"}), 400
    return jsonify({"ok": True, "device_id": device_id, "scopes": scopes})
