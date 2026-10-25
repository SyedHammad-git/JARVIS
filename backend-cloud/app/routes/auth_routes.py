from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, jsonify, request, session

from app.authentication import get_user, verify_password, verify_totp
from app.security import configured_auth_mode, get_client_ip

auth = Blueprint("auth", __name__)
_attempt_lock = threading.Lock()
_attempts: dict[str, deque[float]] = defaultdict(deque)
_locked_until: dict[str, float] = {}
_RATE_WINDOW = 60.0
_LOCKOUT_SECONDS = 300.0
_MAX_ATTEMPTS = 5
_LOGIN_DUMMY_HASH = b"$2b$12$U0h6sL10CwjCA9NgBkqd1eSOv9b4rL8F50qlhSDlkWLVlCAQKIgOe"


def _rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    with _attempt_lock:
        if _locked_until.get(client_ip, 0) > now:
            return True
        entries = _attempts[client_ip]
        while entries and now - entries[0] >= _RATE_WINDOW:
            entries.popleft()
        return len(entries) >= _MAX_ATTEMPTS


def _record_failure(client_ip: str) -> None:
    now = time.monotonic()
    with _attempt_lock:
        entries = _attempts[client_ip]
        while entries and now - entries[0] >= _RATE_WINDOW:
            entries.popleft()
        entries.append(now)
        if len(entries) >= _MAX_ATTEMPTS:
            _locked_until[client_ip] = now + _LOCKOUT_SECONDS


def _clear_failures(client_ip: str) -> None:
    with _attempt_lock:
        _attempts.pop(client_ip, None)
        _locked_until.pop(client_ip, None)


def _csrf_valid() -> bool:
    expected = session.get("login_csrf") or session.get("csrf_token")
    provided = request.headers.get("X-CSRF-Token", "")
    return bool(expected and provided and secrets.compare_digest(expected, provided))


@auth.route("/api/auth/login", methods=["GET", "POST", "OPTIONS"])
def login():
    if configured_auth_mode() == "clerk":
        return jsonify({"ok": False, "error": "local_auth_disabled"}), 404
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "GET":
        csrf_token = secrets.token_urlsafe(32)
        session["login_csrf"] = csrf_token
        session.permanent = True
        return jsonify({"ok": True, "csrf_token": csrf_token})

    if not _csrf_valid():
        return jsonify({"ok": False, "error": "csrf_validation_failed"}), 403

    client_ip = get_client_ip()
    if _rate_limited(client_ip):
        response = jsonify({"ok": False, "error": "login_rate_limited"})
        response.status_code = 429
        response.headers["Retry-After"] = str(int(_LOCKOUT_SECONDS))
        return response

    body = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    totp_code = str(body.get("totp") or "")
    user = get_user(username)
    stored_hash = (user or {}).get("password_hash") or _LOGIN_DUMMY_HASH.decode("ascii")
    valid = verify_password(password, stored_hash)
    valid = valid and bool(user) and not int(user.get("disabled") or 0)
    if valid:
        valid = verify_totp(totp_code, user["totp_secret"])
    if not valid:
        _record_failure(client_ip)
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    _clear_failures(client_ip)
    session.clear()
    session.permanent = True
    session["jarvis_user"] = user["username"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"ok": True, "username": user["username"], "csrf_token": session["csrf_token"]})


@auth.route("/api/auth/logout", methods=["POST", "OPTIONS"])
def logout():
    if request.method == "OPTIONS":
        return "", 204
    session.clear()
    response = jsonify({"ok": True})
    response.delete_cookie(current_app.config.get("SESSION_COOKIE_NAME", "session"), path="/")
    return response


@auth.route("/api/auth/session", methods=["GET"])
def session_status():
    username = session.get("jarvis_user")
    if not username:
        return jsonify({"ok": False, "authenticated": False}), 401
    return jsonify({"ok": True, "authenticated": True, "username": username})
