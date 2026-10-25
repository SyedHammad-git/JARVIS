"""HTTP routes for pairing and device status. Pairing requires a PIN session."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from auth import verify_pin
from config import DEVICE_ID, EXECUTION_MODE
from devices.gateway import is_online
from devices.pairing import get_device_status_cached, issue_device, list_devices, revoke_device
from error_utils import api_errors

log = logging.getLogger("jarvis.devices")

devices_bp = Blueprint("devices", __name__)


def _pin_ok() -> bool:
    if session.get("jarvis_authed"):
        return True
    body = request.get_json(silent=True) or {}
    pin = (
        request.headers.get("X-JARVIS-PIN")
        or request.args.get("pin")
        or body.get("pin")
        or ""
    )
    if pin and verify_pin(str(pin).strip()):
        session["jarvis_authed"] = True
        return True
    return False


def _require_pin():
    if _pin_ok():
        return None
    return jsonify({"ok": False, "error": "PIN required"}), 401


@devices_bp.route("/api/devices/pair", methods=["POST", "OPTIONS"])
@api_errors
def pair_device():
    if request.method == "OPTIONS":
        return "", 204
    denied = _require_pin()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "PC").strip() or "PC"
    device_id, token = issue_device(name)
    # Token returned ONCE. It is not logged and will not appear in GET /api/devices.
    return jsonify({
        "ok": True,
        "device_id": device_id,
        "token": token,
        "name": name,
        "once": True,
        "message": "Save this token now — it will not be shown again.",
    })


@devices_bp.route("/api/devices", methods=["GET"])
@api_errors
def devices_list():
    denied = _require_pin()
    if denied:
        return denied
    rows = list_devices()
    for r in rows:
        r["online"] = is_online(r["device_id"])
    return jsonify({"ok": True, "devices": rows, "count": len(rows)})


@devices_bp.route("/api/devices/<device_id>/revoke", methods=["POST", "OPTIONS"])
@api_errors
def devices_revoke(device_id):
    if request.method == "OPTIONS":
        return "", 204
    denied = _require_pin()
    if denied:
        return denied
    if not revoke_device(device_id):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "device_id": device_id, "revoked": True})


@devices_bp.route("/api/device/status", methods=["GET"])
@api_errors
def device_status():
    device_id = (request.args.get("device_id") or DEVICE_ID or "").strip()
    device = get_device_status_cached(device_id)
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
