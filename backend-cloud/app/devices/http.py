"""HTTP routes for pairing and device status require authenticated ownership."""
from __future__ import annotations

import logging
import hashlib
import re
import time

from flask import Blueprint, g, jsonify, request

from app.config import DEVICE_ID
from app.db import db_write, db_write_returning
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
_PAIR_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")
_PAIR_IP_WINDOW = 300
_PAIR_IP_LIMIT = 10
_PAIR_GLOBAL_WINDOW = 60
_PAIR_GLOBAL_LIMIT = 120
_PAIR_FAILURE_LIMIT = 5
_PAIR_LOCKOUT_SECONDS = 900


def _increment_pair_attempt(rate_key: str, now: float, window: int) -> dict:
    rows = db_write_returning(
        "INSERT INTO pair_code_rate_limits(rate_key,window_start,attempts,failure_window,failures,locked_until) "
        "VALUES(?,?,1,?,0,0) ON CONFLICT(rate_key) DO UPDATE SET "
        "attempts=CASE WHEN ?-pair_code_rate_limits.window_start>=? THEN 1 "
        "ELSE pair_code_rate_limits.attempts+1 END,"
        "window_start=CASE WHEN ?-pair_code_rate_limits.window_start>=? THEN ? "
        "ELSE pair_code_rate_limits.window_start END "
        "RETURNING attempts,locked_until",
        (rate_key, now, now, now, window, now, window, now),
    )
    if not rows:
        raise RuntimeError("pair_code_rate_limit_unavailable")
    return rows[0]


def _pair_ip_rate_key(client_ip: str) -> str:
    return "ip:" + hashlib.sha256(client_ip.encode("utf-8")).hexdigest()


def _check_pair_request(client_ip: str, now: float) -> bool:
    if not db_write(
        "DELETE FROM pair_code_rate_limits WHERE rate_key<>'global' "
        "AND window_start<? AND failure_window<? AND locked_until<?",
        (now - _PAIR_IP_WINDOW, now - _PAIR_IP_WINDOW, now),
    ):
        raise RuntimeError("pair_code_rate_limit_unavailable")
    global_row = _increment_pair_attempt("global", now, _PAIR_GLOBAL_WINDOW)
    ip_row = _increment_pair_attempt(_pair_ip_rate_key(client_ip), now, _PAIR_IP_WINDOW)
    return (
        global_row["attempts"] <= _PAIR_GLOBAL_LIMIT
        and ip_row["attempts"] <= _PAIR_IP_LIMIT
        and float(ip_row["locked_until"]) <= now
    )


def _record_pair_failure(client_ip: str, now: float) -> None:
    rate_key = _pair_ip_rate_key(client_ip)
    rows = db_write_returning(
        "INSERT INTO pair_code_rate_limits(rate_key,window_start,attempts,failure_window,failures,locked_until) "
        "VALUES(?,?,0,?,1,0) ON CONFLICT(rate_key) DO UPDATE SET "
        "failures=CASE WHEN ?-pair_code_rate_limits.failure_window>=? THEN 1 "
        "ELSE pair_code_rate_limits.failures+1 END,"
        "failure_window=CASE WHEN ?-pair_code_rate_limits.failure_window>=? THEN ? "
        "ELSE pair_code_rate_limits.failure_window END "
        "RETURNING failures",
        (rate_key, now, now, now, _PAIR_IP_WINDOW, now, _PAIR_IP_WINDOW, now),
    )
    if not rows:
        raise RuntimeError("pair_code_rate_limit_unavailable")
    if rows[0]["failures"] >= _PAIR_FAILURE_LIMIT:
        if not db_write(
            "UPDATE pair_code_rate_limits SET locked_until=? WHERE rate_key=?",
            (now + _PAIR_LOCKOUT_SECONDS, rate_key),
        ):
            raise RuntimeError("pair_code_rate_limit_unavailable")


def _clear_pair_failures(client_ip: str) -> None:
    if not db_write(
        "UPDATE pair_code_rate_limits SET failures=0,locked_until=0 WHERE rate_key=?",
        (_pair_ip_rate_key(client_ip),),
    ):
        raise RuntimeError("pair_code_rate_limit_unavailable")


def _pair_code_error():
    return jsonify({"ok": False, "error": "pair_code_invalid"}), 400


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
    if not _check_pair_request(client_ip, now):
        return jsonify({"ok": False, "error": "pair_code_rate_limited"}), 429

    body = request.get_json(silent=True) or {}
    code = body.get("code")
    if not isinstance(code, str):
        _record_pair_failure(client_ip, now)
        return _pair_code_error()
    code = code.strip().upper()
    if not _PAIR_CODE_RE.fullmatch(code):
        _record_pair_failure(client_ip, now)
        return _pair_code_error()
    result = redeem_pair_code(code)
    if not result:
        _record_pair_failure(client_ip, now)
        return _pair_code_error()
    _clear_pair_failures(client_ip)
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
    owner = g.current_user["username"]
    device = get_device(device_id, owner)
    if not device or device.get("owner_username") != g.current_user["username"]:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not revoke_device(device_id, owner):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "device_id": device_id, "revoked": True})


@devices_bp.route("/api/device/status", methods=["GET"])
@api_errors
def device_status():
    device_id = (request.args.get("device_id") or DEVICE_ID or "").strip()
    owner = str(
        getattr(g, "device_status", {}).get("owner_username")
        if hasattr(g, "device_status")
        else g.current_user["username"]
    )
    device = get_device_status_cached(device_id, owner)
    if hasattr(g, "device_status"):
        if g.device_status.get("device_id") != device_id:
            return jsonify({"ok": False, "error": "not_found"}), 404
    else:
        full_device = get_device(device_id, owner)
        if not device or not full_device or full_device.get("owner_username") != g.current_user["username"]:
            return jsonify({"ok": False, "error": "not_found"}), 404
    online = is_online(device_id)
    return jsonify({
        "ok": True,
        "device_id": device_id,
        "online": bool(online),
        "revoked": bool(device and int(device.get("revoked") or 0)),
        "label": "online" if online else "offline",
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
