from __future__ import annotations

import hmac
import logging
import os
import threading
from datetime import timedelta

import jwt
from flask import g, jsonify, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

log = logging.getLogger("jarvis.security")

PUBLIC_API_PATHS = {
    "/api/ping",
    "/api/health",
    "/api/auth/login",
    "/api/webhooks/clerk",
}
CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_clerk_jwks_clients = {}
_clerk_jwks_lock = threading.Lock()


def _verify_clerk_token(token: str) -> str | None:
    issuer = os.environ.get("CLERK_ISSUER", "").rstrip("/")
    jwks_url = os.environ.get("CLERK_JWKS_URL", "").strip()
    if not issuer or not jwks_url:
        raise RuntimeError("Clerk bearer authentication requires CLERK_ISSUER and CLERK_JWKS_URL")
    if not issuer.startswith("https://") or not jwks_url.startswith("https://"):
        raise RuntimeError("Clerk issuer and JWKS URL must use HTTPS")
    authorized_parties = configured_authorized_parties()
    if not authorized_parties:
        return None

    import jwt
    from jwt import PyJWKClient

    with _clerk_jwks_lock:
        client = _clerk_jwks_clients.get(jwks_url)
        if client is None:
            client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=5)
            _clerk_jwks_clients[jwks_url] = client
    signing_key = client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        leeway=30,
        options={"require": ["exp", "iat", "sub"]},
    )
    subject = claims.get("sub")
    authorized_party = claims.get("azp")
    if not isinstance(authorized_party, str) or authorized_party not in authorized_parties:
        return None
    return f"clerk:{subject}" if isinstance(subject, str) and subject else None


def configured_authorized_parties() -> list[str]:
    raw = os.environ.get("CLERK_AUTHORIZED_PARTIES", "")
    return [party.strip().rstrip("/") for party in raw.split(",") if party.strip()]


def configured_allowed_clerk_subjects() -> list[str]:
    raw = os.environ.get("ALLOWED_CLERK_SUBJECTS", "")
    return [subject.strip() for subject in raw.split(",") if subject.strip()]


def validate_allowed_clerk_subjects() -> None:
    if configured_auth_mode() != "clerk":
        return
    subjects = configured_allowed_clerk_subjects()
    production = os.environ.get("JARVIS_ENV", "development").strip().lower() == "production"
    if subjects:
        return
    if production and os.environ.get("ALLOW_ANY_CLERK_USER", "").strip() != "1":
        raise RuntimeError(
            "Production startup refused: ALLOWED_CLERK_SUBJECTS is required "
            "unless ALLOW_ANY_CLERK_USER=1"
        )
    if production:
        log.warning("SECURITY WARNING: ALLOW_ANY_CLERK_USER=1 permits every verified Clerk user")
    else:
        log.warning(
            "SECURITY WARNING: ALLOWED_CLERK_SUBJECTS is empty; every verified Clerk user is permitted"
        )


def get_client_ip() -> str:
    return request.remote_addr or "unknown"


def configure_proxy(app) -> int:
    try:
        hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
    except ValueError as exc:
        raise RuntimeError("TRUSTED_PROXY_HOPS must be an integer from 0 to 5") from exc
    if not 0 <= hops <= 5:
        raise RuntimeError("TRUSTED_PROXY_HOPS must be an integer from 0 to 5")
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops)
    return hops


def configured_cors_origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000",
    )
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ORIGINS must contain explicit origins and cannot contain '*'")
    return origins


def validate_production_config() -> None:
    validate_allowed_clerk_subjects()
    if os.environ.get("JARVIS_ENV", "development").lower() != "production":
        return
    auth_mode = configured_auth_mode()
    if auth_mode != "clerk":
        if os.environ.get("ALLOW_LOCAL_AUTH", "").strip() != "1":
            raise RuntimeError("Production startup refused: AUTH_MODE=clerk is required")
        log.critical(
            "SECURITY WARNING: ALLOW_LOCAL_AUTH=1 enables local password/TOTP auth in production"
        )
    if os.environ.get("AUTH_ENABLED", "1") != "1":
        raise RuntimeError("Production startup refused: AUTH_ENABLED must be 1")
    secret = os.environ.get("FLASK_SECRET", "")
    if len(secret) < 32 or len(set(secret)) < 8 or secret.lower() in {"change-me", "secret", "password"}:
        raise RuntimeError("Production startup refused: FLASK_SECRET must be a strong random value of at least 32 characters")
    cors = os.environ.get("CORS_ORIGINS", "").strip()
    if not cors or "*" in [origin.strip() for origin in cors.split(",")]:
        raise RuntimeError("Production startup refused: CORS_ORIGINS must contain explicit origins")
    if not os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError("Production startup refused: DATABASE_URL is required")
    if auth_mode == "clerk":
        if (not os.environ.get("CLERK_ISSUER", "").strip()
                or not os.environ.get("CLERK_JWKS_URL", "").strip()):
            raise RuntimeError("Production startup refused: CLERK_ISSUER and CLERK_JWKS_URL are required")
        authorized_parties = configured_authorized_parties()
        if not authorized_parties:
            raise RuntimeError("Production startup refused: CLERK_AUTHORIZED_PARTIES is required")
        if any(not party.startswith("https://") or "*" in party for party in authorized_parties):
            raise RuntimeError("Production startup refused: authorized parties must be explicit HTTPS origins")
    if not os.environ.get("API_KEY_ENCRYPTION_KEY", "").strip():
        raise RuntimeError("Production startup refused: API_KEY_ENCRYPTION_KEY is required")


def install_api_security(app) -> None:
    @app.before_request
    def guard_api_routes():
        if not request.path.startswith("/api/") or request.path in PUBLIC_API_PATHS:
            return None
        if request.method == "OPTIONS":
            return None

        mode = configured_auth_mode()
        authorization = request.headers.get("Authorization", "")
        is_bearer = authorization.startswith("Bearer ")
        if mode == "clerk":
            if not is_bearer:
                return jsonify({"ok": False, "error": "authentication_required"}), 401
            token = authorization[7:].strip()
            if not token:
                return jsonify({"ok": False, "error": "authentication_required"}), 401
            try:
                username = _verify_clerk_token(token)
            except RuntimeError:
                response = jsonify({"ok": False, "error": "authentication_unavailable"})
                response.status_code = 503
                return response
            except (jwt.InvalidTokenError, jwt.PyJWKClientError, TimeoutError, OSError):
                response = jsonify({"ok": False, "error": "authentication_required"})
                response.status_code = 401
                return response
            if not username:
                return jsonify({"ok": False, "error": "authentication_required"}), 401
            allowed_subjects = configured_allowed_clerk_subjects()
            if allowed_subjects and username not in allowed_subjects:
                return jsonify({"error": "not_allowed"}), 403
            g.current_user = {"username": username, "disabled": 0}
        elif is_bearer:
            return jsonify({"ok": False, "error": "authentication_required"}), 401
        else:
            username = session.get("jarvis_user")
            if username:
                from app.authentication import get_user

                user = get_user(username)
                if user and not int(user.get("disabled") or 0):
                    g.current_user = user
                else:
                    session.clear()
                    username = None

        if username and hasattr(g, "current_user"):
            from app.config import set_user_api_keys
            g.api_key_context_token = set_user_api_keys({})

        if (mode == "local" and not username
                and request.path == "/api/device/status" and request.method == "GET"):
            from app.devices.pairing import get_device
            from app.devices.pairing import hash_token

            device_id = (request.args.get("device_id") or "").strip()
            provided = request.headers.get("X-JARVIS-Device-Token", "")
            device = get_device(device_id) if device_id else None
            stored_hash = (device or {}).get("token_hash") or ("0" * 64)
            if (device and not int(device.get("revoked") or 0)
                    and hmac.compare_digest(str(stored_hash), hash_token(provided))):
                g.device_status = device
                return None

        if not username:
            response = jsonify({"ok": False, "error": "authentication_required"})
            response.status_code = 401
            return response

        if mode == "local" and request.method not in CSRF_SAFE_METHODS:
            expected = session.get("csrf_token", "")
            provided = request.headers.get("X-CSRF-Token", "")
            if not expected or not provided or not hmac.compare_digest(expected, provided):
                response = jsonify({"ok": False, "error": "csrf_validation_failed"})
                response.status_code = 403
                return response
        from app.db import register_owner
        from app.neural import register_heartbeat_owner
        register_owner(username)
        register_heartbeat_owner(username)
        return None

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.path.startswith("/api/") or request.path == "/pairing/redeem-code":
            response.headers["Cache-Control"] = "no-store"
        if request.path in {"/", "/mobile"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        return response

    @app.teardown_request
    def reset_request_api_keys(_error):
        token = getattr(g, "api_key_context_token", None)
        if token is not None:
            from app.config import reset_user_api_keys

            reset_user_api_keys(token)


def configure_session(app) -> None:
    production = os.environ.get("JARVIS_ENV", "development").strip().lower() == "production"
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        AUTH_ENABLED=True,
    )


def configured_auth_mode() -> str:
    mode = os.environ.get("AUTH_MODE", "local").strip().lower()
    if mode not in {"local", "clerk"}:
        raise RuntimeError("AUTH_MODE must be either 'local' or 'clerk'")
    return mode
