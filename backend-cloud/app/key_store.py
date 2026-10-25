from __future__ import annotations

import os
from cryptography.fernet import Fernet, InvalidToken

from app.db import db_read, db_write, ts

PROVIDER_ENV = {
    "groq": "GROQ_KEY",
    "gemini": "GEMINI_KEY",
    "openrouter": "OPENROUTER_KEY",
    "weather": "WEATHER_KEY",
}


class KeyStorageUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("API_KEY_ENCRYPTION_KEY", "")
    if not key:
        raise KeyStorageUnavailable("API_KEY_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise KeyStorageUnavailable("API_KEY_ENCRYPTION_KEY is invalid") from exc


def save_user_key(owner: str, provider: str, key: str) -> None:
    if provider not in PROVIDER_ENV:
        raise ValueError("unsupported_provider")
    encrypted = _fernet().encrypt(key.encode("utf-8")).decode("ascii")
    stored = db_write(
        "INSERT INTO user_api_keys(owner_username,provider,encrypted_key,updated_at) "
        "VALUES(?,?,?,?) ON CONFLICT(owner_username,provider) DO UPDATE SET "
        "encrypted_key=excluded.encrypted_key,updated_at=excluded.updated_at",
        (owner, provider, encrypted, ts()),
    )
    if not stored:
        raise RuntimeError("api_key_storage_failed")


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
    keys = load_user_keys(owner)
    return [
        {
            "provider": provider,
            "configured": bool(keys.get(env_name)),
            "last4": keys[env_name][-4:] if keys.get(env_name) else "",
        }
        for provider, env_name in PROVIDER_ENV.items()
    ]
