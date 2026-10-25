from __future__ import annotations

import re

import bcrypt
import pyotp

from app.db import db_read, db_write, ts

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,80}$")


def get_user(username: str) -> dict | None:
    rows = db_read(
        "SELECT username, password_hash, totp_secret, disabled FROM users WHERE username=?",
        (username,),
    )
    return rows[0] if rows else None


def create_user(username: str, password: str, totp_secret: str) -> bool:
    username = (username or "").strip()
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError("username must be 3-80 characters from letters, digits, . _ @ -")
    if not isinstance(password, str) or len(password.encode("utf-8")) < 12:
        raise ValueError("password must be at least 12 bytes")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("password must not exceed 72 bytes")
    if not isinstance(totp_secret, str) or len(totp_secret) < 16:
        raise ValueError("a valid TOTP secret is required")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    return db_write(
        "INSERT INTO users(username,password_hash,totp_secret,created_at,disabled) VALUES(?,?,?,?,0)",
        (username, password_hash, totp_secret, ts()),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def verify_totp(code: str, secret: str) -> bool:
    try:
        return pyotp.TOTP(secret).verify(str(code).replace(" ", ""), valid_window=1)
    except (ValueError, TypeError):
        return False
