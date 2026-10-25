"""Issue and revoke device pairing tokens. Tokens are shown once; only sha256 is stored."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from threading import Lock

from app.db import db_read, db_write, ts

log = logging.getLogger("jarvis.devices")

_DUMMY_HASH = "0" * 64
DEVICE_STATUS_CACHE_TTL = 60
_device_status_cache_lock = Lock()
_device_status_cache: dict[str, tuple[dict | None, float]] = {}


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def issue_device(name: str) -> tuple[str, str]:
    """Create a device row. Returns (device_id, plaintext_token) — token is never stored."""
    device_id = "dev_" + secrets.token_urlsafe(12)
    token = secrets.token_urlsafe(32)
    now = ts()
    ok = db_write(
        "INSERT INTO devices(device_id,name,token_hash,revoked,created_at,last_seen) "
        "VALUES(?,?,?,0,?,?)",
        (device_id, (name or "PC").strip() or "PC", hash_token(token), now, ""),
    )
    if not ok:
        raise RuntimeError("Failed to store device pairing")
    log.info("Issued device pairing device_id=%s name=%s", device_id, name)
    return device_id, token


def list_devices() -> list[dict]:
    rows = db_read(
        "SELECT device_id, name, revoked, created_at, last_seen FROM devices "
        "ORDER BY created_at DESC"
    )
    out = []
    for r in rows:
        out.append({
            "device_id": r.get("device_id"),
            "name": r.get("name"),
            "revoked": int(r.get("revoked") or 0),
            "created_at": r.get("created_at") or "",
            "last_seen": r.get("last_seen") or "",
        })
    return out


def get_device(device_id: str) -> dict | None:
    rows = db_read(
        "SELECT device_id, name, token_hash, revoked, created_at, last_seen "
        "FROM devices WHERE device_id=?",
        (device_id,),
    )
    return rows[0] if rows else None


def get_device_status_cached(device_id: str) -> dict | None:
    now = time.monotonic()
    with _device_status_cache_lock:
        cached = _device_status_cache.get(device_id)
        if cached and now - cached[1] < DEVICE_STATUS_CACHE_TTL:
            return dict(cached[0]) if cached[0] is not None else None
    rows = db_read(
        "SELECT device_id, revoked FROM devices WHERE device_id=?",
        (device_id,),
    )
    row = rows[0] if rows else None
    with _device_status_cache_lock:
        _device_status_cache[device_id] = (dict(row) if row else None, now)
    return dict(row) if row else None


def invalidate_device_status_cache(device_id: str, revoked: bool | None = None) -> None:
    with _device_status_cache_lock:
        if revoked is None:
            _device_status_cache.pop(device_id, None)
        else:
            _device_status_cache[device_id] = (
                {"device_id": device_id, "revoked": int(revoked)},
                time.monotonic(),
            )


def touch_last_seen(device_id: str) -> None:
    db_write("UPDATE devices SET last_seen=? WHERE device_id=?", (ts(), device_id))


def revoke_device(device_id: str) -> bool:
    row = get_device(device_id)
    if not row:
        return False
    if not db_write("UPDATE devices SET revoked=1 WHERE device_id=?", (device_id,)):
        invalidate_device_status_cache(device_id)
        return False
    invalidate_device_status_cache(device_id, revoked=True)
    log.info("Revoked device_id=%s", device_id)
    try:
        from app.devices.gateway import disconnect_device
        disconnect_device(device_id)
    except Exception as exc:
        log.warning("disconnect after revoke failed device_id=%s: %s", device_id, exc)
    return True


def validate_device_token(device_id: str, token: str) -> dict | None:
    """Constant-time hash compare. Never logs the token. Rejects unknown/revoked."""
    row = get_device(device_id)
    stored = (row or {}).get("token_hash") or _DUMMY_HASH
    incoming = hash_token(token)
    match = hmac.compare_digest(str(stored), incoming)
    if not row or int(row.get("revoked") or 0) or not match:
        return None
    return row
