"""Issue and revoke device pairing tokens. Tokens are shown once; only sha256 is stored."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from threading import Lock

from app.db import db_read, db_write, db_write_returning, ts

log = logging.getLogger("jarvis.devices")

_DUMMY_HASH = "0" * 64
DEFAULT_SCOPES = {
    "allow_open_app": False,
    "allow_camera": False,
    "allow_notify": False,
    "allow_lock": False,
    "allow_system_stats": False,
}
ALLOWED_SCOPE_NAMES = frozenset(DEFAULT_SCOPES)
DEVICE_STATUS_CACHE_TTL = 60
PAIR_CODE_TTL_SECONDS = 600
PAIR_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_device_status_cache_lock = Lock()
_device_status_cache: dict[tuple[str, str], tuple[dict | None, float]] = {}


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def create_pair_code(owner_username: str, name: str = "PC") -> tuple[str, float]:
    db_write(
        "DELETE FROM pairing_codes WHERE owner_username=?",
        (owner_username,),
    )
    for _ in range(5):
        code = "".join(secrets.choice(PAIR_CODE_ALPHABET) for _ in range(8))
        expires_at = time.time() + PAIR_CODE_TTL_SECONDS
        created = db_write(
            "INSERT INTO pairing_codes(code_hash,owner_username,name,expires_at) VALUES(?,?,?,?)",
            (hash_token(code), owner_username, name, expires_at),
        )
        if created:
            return code, expires_at
    raise RuntimeError("Failed to create a unique device pairing code")


def redeem_pair_code(code: str) -> tuple[str, str, str] | None:
    supplied_hash = hash_token(code)
    rows = db_write_returning(
        "DELETE FROM pairing_codes WHERE code_hash=? AND expires_at>? RETURNING owner_username,name",
        (supplied_hash, time.time()),
    )
    if not rows:
        return None
    owner, name = rows[0]["owner_username"], rows[0]["name"]
    device_id, token = issue_device(name, owner)
    return device_id, token, name


def issue_device(name: str, owner_username: str) -> tuple[str, str]:
    """Create a device row. Returns (device_id, plaintext_token) — token is never stored."""
    device_id = "dev_" + secrets.token_urlsafe(12)
    token = secrets.token_urlsafe(32)
    now = ts()
    ok = db_write(
        "INSERT INTO devices(device_id,name,token_hash,owner_username,scopes,revoked,created_at,last_seen) "
        "VALUES(?,?,?,?,?,0,?,?)",
        (
            device_id,
            (name or "PC").strip() or "PC",
            hash_token(token),
            owner_username,
            json.dumps(DEFAULT_SCOPES, sort_keys=True),
            now,
            "",
        ),
    )
    if not ok:
        raise RuntimeError("Failed to store device pairing")
    log.info("Issued device pairing device_id=%s name=%s", device_id, name)
    return device_id, token


def list_devices(owner_username: str) -> list[dict]:
    rows = db_read(
        "SELECT device_id, name, revoked, created_at, last_seen FROM devices "
        "WHERE owner_username=? ORDER BY created_at DESC",
        (owner_username,),
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


def set_device_scopes(device_id: str, owner_username: str, scopes: dict) -> bool:
    if not isinstance(scopes, dict) or set(scopes) != ALLOWED_SCOPE_NAMES:
        return False
    if any(type(value) is not bool for value in scopes.values()):
        return False
    return db_write(
        "UPDATE devices SET scopes=? WHERE device_id=? AND owner_username=? AND revoked=0",
        (json.dumps(scopes, sort_keys=True), device_id, owner_username),
    )


def device_scope_for_action(action: str, args: dict | None = None) -> str | None:
    scope_name = {
        "open_app": "allow_open_app",
        "open_url": "allow_open_app",
        "take_snapshot": "allow_camera",
        "notify": "allow_notify",
        "lock_screen": "allow_lock",
        "system_stats": "allow_system_stats",
    }.get(action)
    return scope_name


def device_scope_allows(device: dict, action: str, args: dict | None = None) -> bool:
    scope_name = device_scope_for_action(action, args)
    if not scope_name:
        return False
    try:
        scopes = json.loads(device.get("scopes") or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    return scopes.get(scope_name) is True


def get_device(device_id: str, owner_username: str | None = None) -> dict | None:
    owner_filter = " AND owner_username=?" if owner_username is not None else ""
    params = (device_id, owner_username) if owner_username is not None else (device_id,)
    rows = db_read(
        "SELECT device_id, name, token_hash, owner_username, scopes, revoked, created_at, last_seen "
        f"FROM devices WHERE device_id=?{owner_filter}",
        params,
    )
    return rows[0] if rows else None


def get_device_status_cached(
    device_id: str, owner_username: str
) -> dict | None:
    cache_key = (owner_username, device_id)
    now = time.monotonic()
    with _device_status_cache_lock:
        cached = _device_status_cache.get(cache_key)
        if cached and now - cached[1] < DEVICE_STATUS_CACHE_TTL:
            return dict(cached[0]) if cached[0] is not None else None
    rows = db_read(
        "SELECT device_id, revoked FROM devices WHERE device_id=? AND owner_username=?",
        (device_id, owner_username),
    )
    row = rows[0] if rows else None
    with _device_status_cache_lock:
        _device_status_cache[cache_key] = (dict(row) if row else None, now)
    return dict(row) if row else None


def invalidate_device_status_cache(
    device_id: str,
    revoked: bool | None = None,
    owner_username: str | None = None,
) -> None:
    with _device_status_cache_lock:
        if revoked is None:
            keys = [
                key for key in _device_status_cache
                if key[1] == device_id and (owner_username is None or key[0] == owner_username)
            ]
            for key in keys:
                _device_status_cache.pop(key, None)
        else:
            _device_status_cache[(owner_username or "", device_id)] = (
                {"device_id": device_id, "revoked": int(revoked)},
                time.monotonic(),
            )


def touch_last_seen(device_id: str, owner_username: str) -> None:
    db_write(
        "UPDATE devices SET last_seen=? WHERE device_id=? AND owner_username=?",
        (ts(), device_id, owner_username),
    )


def revoke_device(device_id: str, owner_username: str) -> bool:
    row = get_device(device_id, owner_username)
    if not row:
        return False
    if not db_write(
        "UPDATE devices SET revoked=1 WHERE device_id=? AND owner_username=?",
        (device_id, owner_username),
    ):
        invalidate_device_status_cache(device_id)
        return False
    invalidate_device_status_cache(device_id, revoked=True, owner_username=owner_username)
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
