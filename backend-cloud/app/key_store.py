from __future__ import annotations

import hmac
import os
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import reset_user_api_keys, set_user_api_keys
from app.db import db_read, db_scalar, db_write, register_owner, ts

PROVIDER_ENV = {
    "groq": "GROQ_KEY",
    "gemini": "GEMINI_KEY",
    "openrouter": "OPENROUTER_KEY",
    "weather": "WEATHER_KEY",
}


class KeyStorageUnavailable(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    configured = [
        os.environ.get("API_KEY_ENCRYPTION_KEY", ""),
        os.environ.get("API_KEY_ENCRYPTION_KEY_OLD", ""),
    ]
    if not configured[0]:
        raise KeyStorageUnavailable("API key encryption is not configured")
    try:
        return MultiFernet([Fernet(value.encode("ascii")) for value in configured if value])
    except (ValueError, UnicodeError) as exc:
        raise KeyStorageUnavailable("API key encryption configuration is invalid") from exc


def current_key_version(owner: str) -> int:
    configured_version = 2 if os.environ.get("API_KEY_ENCRYPTION_KEY_OLD", "") else 1
    stored_version = db_scalar(
        "SELECT MAX(key_version) FROM user_api_keys WHERE owner_username=?",
        (owner,),
    )
    return max(configured_version, int(stored_version or 1))


@contextmanager
def user_api_key_context(owner: str):
    token = set_user_api_keys(load_user_keys(owner))
    try:
        yield
    finally:
        reset_user_api_keys(token)


def save_user_key(owner: str, provider: str, key: str) -> None:
    if provider not in PROVIDER_ENV:
        raise ValueError("unsupported_provider")
    encrypted = _fernet().encrypt(key.encode("utf-8")).decode("ascii")
    stored = db_write(
        "INSERT INTO user_api_keys(owner_username,provider,encrypted_key,key_version,last4,status,last_tested_at,updated_at) "
        "VALUES(?,?,?,?,?,'saved','',?) ON CONFLICT(owner_username,provider) DO UPDATE SET "
        "encrypted_key=excluded.encrypted_key,key_version=excluded.key_version,"
        "last4=excluded.last4,status='saved',last_tested_at='',updated_at=excluded.updated_at",
        (owner, provider, encrypted, current_key_version(owner), key[-4:], ts()),
    )
    if not stored:
        raise RuntimeError("api_key_storage_failed")
    register_owner(owner)


def delete_user_key(owner: str, provider: str) -> None:
    if provider not in PROVIDER_ENV:
        raise ValueError("unsupported_provider")
    if not db_write(
        "DELETE FROM user_api_keys WHERE owner_username=? AND provider=?",
        (owner, provider),
    ):
        raise RuntimeError("api_key_storage_failed")


def load_user_keys(owner: str) -> dict[str, str]:
    rows = db_read(
        "SELECT provider,encrypted_key FROM user_api_keys WHERE owner_username=?",
        (owner,),
    )
    if not rows:
        return {}
    cipher = _fernet()
    keys = {}
    try:
        for row in rows:
            env_name = PROVIDER_ENV.get(row["provider"])
            if env_name:
                keys[env_name] = cipher.decrypt(row["encrypted_key"].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise KeyStorageUnavailable("Stored provider key could not be decrypted") from exc
    return keys


def list_user_keys(owner: str) -> list[dict]:
    rows = db_read(
        "SELECT provider,last4,status,last_tested_at FROM user_api_keys WHERE owner_username=?",
        (owner,),
    )
    configured = {row["provider"]: row for row in rows}
    return [
        {
            "provider": provider,
            "configured": provider in configured,
            "last4": configured.get(provider, {}).get("last4", ""),
            "status": configured.get(provider, {}).get("status", "not_configured"),
            "last_tested_at": configured.get(provider, {}).get("last_tested_at", ""),
        }
        for provider in PROVIDER_ENV
    ]


def update_key_test_status(owner: str, provider: str, supplied_key: str, valid: bool) -> None:
    if provider not in PROVIDER_ENV:
        raise ValueError("unsupported_provider")
    rows = db_read(
        "SELECT encrypted_key FROM user_api_keys WHERE owner_username=? AND provider=?",
        (owner, provider),
    )
    if not rows:
        return
    try:
        stored_key = _fernet().decrypt(rows[0]["encrypted_key"].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise KeyStorageUnavailable("Stored provider key could not be decrypted") from exc
    if hmac.compare_digest(stored_key, supplied_key):
        status = "valid" if valid else "invalid"
        if not db_write(
            "UPDATE user_api_keys SET status=?,last_tested_at=?,updated_at=? "
            "WHERE owner_username=? AND provider=?",
            (status, ts(), ts(), owner, provider),
        ):
            raise RuntimeError("api_key_storage_failed")


def rotate_user_keys(*, dry_run: bool = False) -> int:
    """Re-encrypt all stored keys using the primary key; return rows processed."""
    cipher = _fernet()
    primary = Fernet(os.environ["API_KEY_ENCRYPTION_KEY"].encode("ascii"))
    owners = db_read("SELECT owner_username FROM user_owners ORDER BY owner_username")
    processed = 0
    for owner_row in owners:
        owner = str(owner_row.get("owner_username") or "")
        if not owner:
            continue
        rows = db_read(
            "SELECT provider,encrypted_key FROM user_api_keys WHERE owner_username=?",
            (owner,),
        )
        if dry_run:
            processed += len(rows)
            continue
        for row in rows:
            try:
                plaintext = cipher.decrypt(row["encrypted_key"].encode("ascii"))
                encrypted = primary.encrypt(plaintext).decode("ascii")
            except (InvalidToken, ValueError, UnicodeError) as exc:
                raise KeyStorageUnavailable("Stored provider key could not be rotated") from exc
            if not db_write(
                "UPDATE user_api_keys SET encrypted_key=?,key_version=?,updated_at=? "
                "WHERE owner_username=? AND provider=?",
                (
                    encrypted,
                    current_key_version(owner),
                    ts(),
                    owner,
                    row["provider"],
                ),
            ):
                raise RuntimeError("api_key_rotation_failed")
            processed += 1
    return processed
