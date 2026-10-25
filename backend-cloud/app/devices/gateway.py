"""Socket.IO /device namespace — the cloud talks to one paired PC."""
from __future__ import annotations

import logging
import secrets
import time
import uuid
from threading import Lock

from flask import request
from flask_socketio import Namespace, disconnect
from socketio.exceptions import ConnectionRefusedError, TimeoutError as SocketIOTimeout

from app.auth import add_alert
from app.devices.pairing import (
    device_scope_allows,
    device_scope_for_action,
    get_device,
    get_device_status_cached,
    list_devices,
    touch_last_seen,
    validate_device_token,
)
from app.extensions import socketio
from app.notifications import send_discord_alert

log = logging.getLogger("jarvis.devices")

_map_lock = Lock()
_sid_by_device: dict[str, str] = {}
_device_by_sid: dict[str, str] = {}

CALL_TIMEOUT = 20


def is_online(device_id: str | None) -> bool:
    if not device_id:
        return False
    with _map_lock:
        return device_id in _sid_by_device


def online_device_ids() -> list[str]:
    with _map_lock:
        return list(_sid_by_device)


def first_online_device(owner_username: str) -> str | None:
    for device in list_devices(owner_username):
        device_id = device.get("device_id")
        if (device_id and not int(device.get("revoked") or 0)
                and is_online(device_id)):
            return str(device_id)
    return None


def sid_for(device_id: str) -> str | None:
    with _map_lock:
        return _sid_by_device.get(device_id)


def disconnect_device(device_id: str) -> None:
    with _map_lock:
        sid = _sid_by_device.pop(device_id, None)
        if sid:
            _device_by_sid.pop(sid, None)
    if sid:
        try:
            socketio.server.disconnect(sid, namespace="/device")
        except Exception as exc:
            log.info("disconnect_device: %s", exc)


def call_device(
    device_id: str,
    action: str,
    args: dict | None = None,
    timeout: int = CALL_TIMEOUT,
    *,
    owner_username: str | None = None,
    confirmed: bool = False,
    confirmation_nonce: str | None = None,
) -> dict:
    """Send command to the paired device; wait for ack. Never raises to the agent."""
    device = get_device(device_id)
    if not device:
        return {"ok": False, "error": "device_offline"}
    if not owner_username or device.get("owner_username") != owner_username:
        return {"ok": False, "error": "device_not_owned"}
    if int(device.get("revoked") or 0):
        return {"ok": False, "error": "device_revoked"}
    scope = device_scope_for_action(action, args)
    if not scope or not device_scope_allows(device, action, args):
        return {"ok": False, "error": "device_scope_denied"}
    high_risk = action in {"lock_screen"}
    if high_risk and (not confirmed or not confirmation_nonce):
        return {"ok": False, "error": "needs_confirmation"}
    sid = sid_for(device_id)
    if not sid:
        return {"ok": False, "error": "device_offline"}
    payload = {
        "id": str(uuid.uuid4()),
        "nonce": confirmation_nonce or secrets.token_urlsafe(24),
        "timestamp": int(time.time() * 1000),
        "action": action,
        "scope": scope,
        "risk": "high" if high_risk else "low",
        "args": args or {},
    }
    try:
        ack = socketio.call(
            "command", payload, namespace="/device", to=sid, timeout=timeout,
        )
    except (SocketIOTimeout, TimeoutError):
        return {"ok": False, "error": "device_timeout"}
    except Exception as exc:
        log.warning("call_device failed action=%s device_id=%s: %s", action, device_id, exc)
        return {"ok": False, "error": "device_timeout"}
    if not isinstance(ack, dict) or "ok" not in ack:
        return {"ok": False, "error": "device_timeout"}
    return ack


def _bind(device_id: str, sid: str) -> str | None:
    """Newest connection wins. Returns the previous sid to drop, if any."""
    with _map_lock:
        old = _sid_by_device.get(device_id)
        if old and old != sid:
            _device_by_sid.pop(old, None)
        _sid_by_device[device_id] = sid
        _device_by_sid[sid] = device_id
        return old if old and old != sid else None


def _unbind_sid(sid: str) -> None:
    with _map_lock:
        device_id = _device_by_sid.pop(sid, None)
        if device_id and _sid_by_device.get(device_id) == sid:
            _sid_by_device.pop(device_id, None)


class DeviceNamespace(Namespace):
    def on_connect(self, auth=None):
        auth = auth or {}
        device_id = str(auth.get("device_id") or "")
        token = str(auth.get("token") or "")
        device = get_device(device_id)
        if device and int(device.get("revoked") or 0):
            raise ConnectionRefusedError({"error": "device_revoked"})
        row = validate_device_token(device_id, token)
        if not row:
            log.warning("device connect rejected device_id=%s", device_id or "(missing)")
            return False
        sid = request.sid
        old = _bind(device_id, sid)
        if old:
            try:
                disconnect(old, namespace="/device")
            except Exception:
                pass
            log.info("device replaced previous socket device_id=%s", device_id)
        touch_last_seen(device_id)
        log.info("device connected device_id=%s", device_id)
        return True

    def on_disconnect(self):
        sid = getattr(request, "sid", None)
        if sid:
            _unbind_sid(sid)

    def on_alert(self, data):
        self._inbound("alert", data)

    def on_motion(self, data):
        self._inbound("motion", data)

    def on_event(self, data):
        self._inbound("event", data)

    def _inbound(self, kind: str, data):
        sid = getattr(request, "sid", None)
        with _map_lock:
            device_id = _device_by_sid.get(sid, "")
        if not device_id:
            return
        if not isinstance(data, dict):
            data = {"message": str(data)}
        msg = str(data.get("message") or data.get("msg") or kind)[:300]
        log.info("device inbound kind=%s device_id=%s", kind, device_id)
        device = get_device(device_id)
        owner = str((device or {}).get("owner_username") or "")
        add_alert(f"Device {device_id}: {msg}", owner_username=owner)
        try:
            send_discord_alert(f"[{kind}] {device_id}: {msg}", owner_username=owner)
        except Exception:
            pass


def register_namespace(sio=None) -> None:
    (sio or socketio).on_namespace(DeviceNamespace("/device"))
