from __future__ import annotations

import hmac
import logging
import os
import threading
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

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
    raw = os.environ.get("AUTHORIZED_PARTIES", os.environ.get("CLERK_AUTHORIZED_PARTIES", ""))
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
    if not origins or any(not _is_origin(origin) for origin in origins):
        raise RuntimeError("CORS_ORIGINS must contain exact origins and cannot contain '*'")
    return origins


def _is_https_url(value: str, *, origin_only: bool = False) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and "*" not in value
            and not parsed.query
            and not parsed.fragment
            and (not origin_only or parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
        )
    except ValueError:
        return False


def _is_origin(value: str, *, https_only: bool = False) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in ({"https"} if https_only else {"https", "http"})
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and "*" not in value
        )
    except ValueError:
        return False


def production_config_errors(env=None) -> list[str]:
    values = os.environ if env is None else env
    error_names = []

    def require(condition: bool, name: str) -> None:
        if not condition:
            error_names.append(name)

    require(values.get("JARVIS_ENV", "").strip().lower() == "production", "JARVIS_ENV")
    require(values.get("AUTH_MODE", "").strip().lower() == "clerk", "AUTH_MODE")
    require(values.get("AUTH_ENABLED", "1").strip() == "1", "AUTH_ENABLED")

    issuer = values.get("CLERK_ISSUER", "").strip()
    jwks_url = values.get("CLERK_JWKS_URL", "").strip()
    parties_raw = values.get("AUTHORIZED_PARTIES", values.get("CLERK_AUTHORIZED_PARTIES", ""))
    parties = [part.strip() for part in parties_raw.split(",") if part.strip()]
    require(_is_https_url(issuer), "CLERK_ISSUER")
    require(_is_https_url(jwks_url), "CLERK_JWKS_URL")
    require(bool(parties) and all(_is_origin(party, https_only=True) for party in parties), "AUTHORIZED_PARTIES")

    subjects = [item.strip() for item in values.get("ALLOWED_CLERK_SUBJECTS", "").split(",") if item.strip()]
    allow_any_user = values.get("ALLOW_ANY_CLERK_USER", "").strip() == "1"
    require(
        (bool(subjects) and all(subject.startswith("clerk:") for subject in subjects)) or allow_any_user,
        "ALLOWED_CLERK_SUBJECTS",
    )

    secret = values.get("FLASK_SECRET", "")
    require(
        len(secret) >= 32 and len(set(secret)) >= 8
        and secret.lower() not in {"change-me", "secret", "password"},
        "FLASK_SECRET",
    )

    cors_raw = values.get("CORS_ORIGINS", "")
    cors_origins = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]
    require(bool(cors_origins) and all(_is_origin(origin, https_only=True) for origin in cors_origins), "CORS_ORIGINS")

    database_url = values.get("DATABASE_URL", "").strip()
    try:
        database = urlsplit(database_url)
        query = parse_qs(database.query)
        local_smoke_host = database.hostname in {"localhost", "127.0.0.1", "::1"}
        database_valid = (
            database.scheme in {"postgres", "postgresql"}
            and bool(database.hostname)
            and (
                "-pooler" in database.hostname.lower()
                or values.get("JARVIS_SMOKE_TEST", "") == "1" and local_smoke_host
            )
            and query.get("sslmode", [""])[0] in {"require", "verify-ca", "verify-full"}
        )
    except ValueError:
        database_valid = False
    require(database_valid, "DATABASE_URL")
    require(values.get("DB_BACKEND", "").strip().lower() == "postgres", "DB_BACKEND")
    require(values.get("SERVER_FALLBACK_KEYS", "").strip() != "1", "SERVER_FALLBACK_KEYS")

    try:
        from cryptography.fernet import Fernet
        encryption_key = values.get("API_KEY_ENCRYPTION_KEY", "").strip()
        Fernet(encryption_key.encode("ascii"))
        encryption_key_valid = True
    except (ImportError, ValueError, UnicodeError):
        encryption_key_valid = False
    require(encryption_key_valid, "API_KEY_ENCRYPTION_KEY")
    require(_is_https_url(values.get("LANDING_URL", "").strip(), origin_only=True), "LANDING_URL")

    try:
        proxy_hops = int(values.get("TRUSTED_PROXY_HOPS", "0"))
        proxy_valid = 0 <= proxy_hops <= 5
    except (TypeError, ValueError):
        proxy_valid = False
    require(proxy_valid, "TRUSTED_PROXY_HOPS")
    return error_names


def validate_production_config() -> None:
    validate_allowed_clerk_subjects()
    if os.environ.get("JARVIS_ENV", "development").lower() != "production":
        return
    errors = production_config_errors()
    if errors:
        raise RuntimeError(f"Production startup refused: invalid configuration ({', '.join(errors)})")


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
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if os.environ.get("JARVIS_ENV", "development").strip().lower() == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
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
