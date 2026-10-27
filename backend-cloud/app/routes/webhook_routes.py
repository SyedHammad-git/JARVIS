"""Verified Clerk lifecycle webhooks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from flask import Blueprint, jsonify, request

from app.db import DB_BACKEND, db_read, db_write_many
from app.devices.gateway import disconnect_device
from app.config import cache, stat_lock
from app.neural import forget_alarm_owner, purge_owner_state
from app.monitor import forget_monitor_owner
from app.vision.snapshots import purge_owner_snapshots

webhooks = Blueprint("webhooks", __name__)
_SVIX_TOLERANCE_SECONDS = 300


def _verify_svix_request() -> bool:
    secret = os.environ.get("CLERK_WEBHOOK_SECRET", "").strip()
    message_id = request.headers.get("svix-id", "")
    timestamp = request.headers.get("svix-timestamp", "")
    signatures = request.headers.get("svix-signature", "")
    if not secret or not message_id or not timestamp or not signatures:
        return False
    try:
        timestamp_value = int(timestamp)
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - timestamp_value) > _SVIX_TOLERANCE_SECONDS:
        return False
    signed_content = message_id.encode() + b"." + timestamp.encode() + b"." + request.get_data()
    expected = base64.b64encode(
        hmac.new(key, signed_content, hashlib.sha256).digest()
    ).decode("ascii")
    return any(
        version == "v1" and hmac.compare_digest(value, expected)
        for signature in signatures.split()
        for version, separator, value in [signature.partition(",")]
        if separator
    )


def _purge_clerk_user(owner_username: str) -> None:
    devices = db_read(
        "SELECT device_id FROM devices WHERE owner_username=?",
        (owner_username,),
    )
    for row in devices:
        disconnect_device(str(row.get("device_id") or ""))
    tables = [
        (f"DELETE FROM {table} WHERE owner_username=?", (owner_username,))
        for table in (
            "conversations", "notes", "alarms", "memory_facts", "monitors",
            "monitor_log", "command_log", "events", "heartbeat_log", "session_stats",
            "cameras", "user_api_keys", "devices", "user_owners",
            "pairing_codes", "pending_confirmations", "smarthome_devices", "discord_settings",
        )
    ]
    if DB_BACKEND == "postgres":
        tables.extend([
            ("DELETE FROM memory_vectors WHERE owner_username=?", (owner_username,)),
            ("DELETE FROM snapshots WHERE owner_username=?", (owner_username,)),
        ])
    if not db_write_many(tables):
        raise RuntimeError("clerk_user_purge_failed")
    if DB_BACKEND != "postgres":
        purge_owner_snapshots(owner_username)
    forget_alarm_owner(owner_username)
    forget_monitor_owner(owner_username)
    purge_owner_state(owner_username)
    with stat_lock:
        cache["alerts"] = [
            alert for alert in cache["alerts"]
            if alert.get("owner_username") != owner_username
        ]


@webhooks.route("/api/webhooks/clerk", methods=["POST"])
def clerk_webhook():
    if not _verify_svix_request():
        return jsonify({"ok": False, "error": "invalid_webhook_signature"}), 401
    try:
        payload = json.loads(request.get_data())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"ok": False, "error": "invalid_webhook_payload"}), 400
    if payload.get("type") != "user.deleted":
        return jsonify({"ok": True})
    subject = (payload.get("data") or {}).get("id")
    if not isinstance(subject, str) or not subject:
        return jsonify({"ok": False, "error": "invalid_webhook_payload"}), 400
    _purge_clerk_user(f"clerk:{subject}")
    return jsonify({"ok": True})
