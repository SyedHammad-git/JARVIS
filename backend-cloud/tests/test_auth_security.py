import re
import uuid
from datetime import datetime, timezone

import pyotp
import pytest
from cryptography.fernet import Fernet
from flask import Flask, jsonify, request
from werkzeug.routing import UUIDConverter

from app import create_app
from app.authentication import create_user
from app.security import (
    configure_session,
    configure_proxy,
    configured_cors_origins,
    get_client_ip,
    production_config_errors,
    validate_production_config,
)

PUBLIC_API = {"/api/ping", "/api/health", "/api/auth/login", "/api/webhooks/clerk"}


def _rule_path(app, rule, method):
    values = {}
    for name, converter in rule._converters.items():
        class_name = type(converter).__name__
        if class_name == "IntegerConverter":
            values[name] = 1
        elif class_name == "FloatConverter":
            values[name] = 1.0
        elif isinstance(converter, UUIDConverter):
            values[name] = uuid.UUID("12345678-1234-5678-1234-567812345678")
        elif class_name == "PathConverter":
            values[name] = "sample/path"
        else:
            values[name] = "security-test"
    return app.url_map.bind("localhost").build(rule.endpoint, values=values, method=method)


def test_all_api_rules_require_auth_except_explicit_public_routes():
    app = create_app(testing=True)
    client = app.test_client()
    api_rules = [rule for rule in app.url_map.iter_rules() if rule.rule.startswith("/api/")]

    assert api_rules
    for rule in api_rules:
        if rule.rule in PUBLIC_API:
            continue
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        assert methods, rule.rule
        for method in methods:
            response = client.open(_rule_path(app, rule, method), method=method)
            assert response.status_code == 401, f"{method} {rule.rule} was not guarded"

    assert client.get("/api/ping").status_code == 200
    health = client.get("/api/health")
    assert health.status_code == 200
    assert {
        "status", "version", "db_ok", "db_backend", "neon_select_1_latency_ms",
        "pgvector_row_count", "sqlite_fallback_active", "online_device_count",
    } == set(health.get_json())
    assert client.get("/api/auth/login").status_code == 200


def test_login_requires_csrf_and_password_totp_session(monkeypatch):
    from app.routes import auth_routes

    auth_routes._attempts.clear()
    auth_routes._locked_until.clear()
    secret = pyotp.random_base32()
    assert create_user("c1-user", "a-strong-test-password", secret)
    client = create_app(testing=True).test_client()

    blocked = client.post("/api/auth/login", json={"username": "c1-user"})
    assert blocked.status_code == 403

    csrf = client.get("/api/auth/login").get_json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={
            "username": "c1-user",
            "password": "a-strong-test-password",
            "totp": pyotp.TOTP(secret).now(),
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert response.headers.get("Set-Cookie", "").find("HttpOnly") >= 0
    assert "Secure" not in response.headers.get("Set-Cookie", "")
    assert "SameSite=Strict" in response.headers.get("Set-Cookie", "")

    csrf_after_login = response.get_json()["csrf_token"]
    protected = client.post(
        "/api/agent/clear",
        json={},
        headers={"X-CSRF-Token": csrf_after_login},
    )
    assert protected.status_code != 401


def test_session_cookie_secure_flag_tracks_environment(monkeypatch):
    app = Flask("session-cookie-test")
    monkeypatch.setenv("JARVIS_ENV", "development")
    configure_session(app)
    assert app.config["SESSION_COOKIE_SECURE"] is False

    monkeypatch.setenv("JARVIS_ENV", "production")
    configure_session(app)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_login_rate_limits_after_five_failed_attempts():
    from app.routes import auth_routes

    auth_routes._attempts.clear()
    auth_routes._locked_until.clear()
    client = create_app(testing=True).test_client()
    csrf = client.get("/api/auth/login").get_json()["csrf_token"]
    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"username": "missing-user", "password": "wrong", "totp": "000000"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 401
    throttled = client.post(
        "/api/auth/login",
        json={"username": "missing-user", "password": "wrong", "totp": "000000"},
        headers={"X-CSRF-Token": csrf},
    )
    assert throttled.status_code == 429


def test_clerk_mode_rejects_sessions_and_disables_local_login(monkeypatch):
    from app import security

    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("ALLOWED_CLERK_SUBJECTS", "clerk:user-1")
    client = create_app(testing=True).test_client()
    with client.session_transaction() as flask_session:
        flask_session["jarvis_user"] = "local-account"

    assert client.get("/api/auth/login").status_code == 404
    assert client.get("/api/stats").status_code == 401

    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "clerk:user-1")
    response = client.get("/api/stats", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200


def test_clerk_subject_allowlist_allows_listed_user_and_denies_other_user(monkeypatch):
    from app import security

    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("ALLOWED_CLERK_SUBJECTS", "clerk:allowed-user")
    monkeypatch.setattr(
        security,
        "_verify_clerk_token",
        lambda token: {
            "allowed-token": "clerk:allowed-user",
            "other-token": "clerk:other-user",
        }.get(token),
    )
    client = create_app(testing=True).test_client()

    allowed = client.get("/api/stats", headers={"Authorization": "Bearer allowed-token"})
    denied = client.get("/api/stats", headers={"Authorization": "Bearer other-token"})

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.get_json() == {"error": "not_allowed"}


def test_empty_clerk_subject_allowlist_warns_in_development(monkeypatch, caplog):
    from app.security import validate_allowed_clerk_subjects

    monkeypatch.setenv("JARVIS_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("ALLOWED_CLERK_SUBJECTS", "")
    with caplog.at_level("WARNING", logger="jarvis.security"):
        validate_allowed_clerk_subjects()
    assert "ALLOWED_CLERK_SUBJECTS is empty" in caplog.text


def test_production_clerk_requires_subject_allowlist_unless_explicitly_overridden(monkeypatch):
    from app.security import validate_allowed_clerk_subjects

    monkeypatch.setenv("JARVIS_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.delenv("SERVER_FALLBACK_KEYS", raising=False)
    monkeypatch.setenv("ALLOWED_CLERK_SUBJECTS", "")
    monkeypatch.delenv("ALLOW_ANY_CLERK_USER", raising=False)
    with pytest.raises(RuntimeError, match="ALLOWED_CLERK_SUBJECTS"):
        validate_allowed_clerk_subjects()

    monkeypatch.setenv("ALLOW_ANY_CLERK_USER", "1")
    validate_allowed_clerk_subjects()

    monkeypatch.delenv("ALLOW_ANY_CLERK_USER", raising=False)
    with pytest.raises(RuntimeError, match="ALLOWED_CLERK_SUBJECTS"):
        create_app(testing=True)


def test_production_requires_clerk_auth_even_with_local_auth_override(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "production")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.delenv("SERVER_FALLBACK_KEYS", raising=False)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.delenv("ALLOW_LOCAL_AUTH", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        validate_production_config()

    monkeypatch.setenv("ALLOW_LOCAL_AUTH", "1")
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        validate_production_config()


def test_proxyfix_trusts_forwarded_ip_only_when_hops_configured(monkeypatch):
    app = Flask("proxy-test")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    configure_proxy(app)

    @app.get("/")
    def client_ip():
        return jsonify({"ip": get_client_ip()})

    response = app.test_client().get("/", headers={"X-Forwarded-For": "203.0.113.44"})
    assert response.get_json()["ip"] != "203.0.113.44"

    forwarded_app = Flask("proxy-trusted-test")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    configure_proxy(forwarded_app)

    @forwarded_app.get("/")
    def forwarded_ip():
        return jsonify({"ip": get_client_ip()})

    response = forwarded_app.test_client().get(
        "/", headers={"X-Forwarded-For": "203.0.113.44"}
    )
    assert response.get_json()["ip"] == "203.0.113.44"


def test_security_headers_and_explicit_cors(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://jarvis.example.test")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://jarvis.example.test")
    app = create_app(testing=True)
    response = app.test_client().get(
        "/", headers={"Origin": "https://jarvis.example.test"}
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Access-Control-Allow-Origin"] == "https://jarvis.example.test"
    api = app.test_client().get("/api/ping")
    assert api.headers["Cache-Control"] == "no-store"


def test_production_security_headers_include_transport_and_permissions(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "production")
    app = Flask("production-header-test")
    from app.security import install_api_security
    install_api_security(app)
    response = app.test_client().get("/")
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["X-Permitted-Cross-Domain-Policies"] == "none"


def test_production_config_shape_validation_uses_names_only():
    env = {
        "JARVIS_ENV": "production",
        "AUTH_MODE": "clerk",
        "AUTH_ENABLED": "1",
        "CLERK_ISSUER": "https://clerk.example.test",
        "CLERK_JWKS_URL": "https://clerk.example.test/.well-known/jwks.json",
        "AUTHORIZED_PARTIES": "https://jarvis.example.test",
        "ALLOWED_CLERK_SUBJECTS": "clerk:test-user",
        "FLASK_SECRET": "synthetic-production-secret-0123456789abcdef",
        "CORS_ORIGINS": "https://jarvis.example.test",
        "DATABASE_URL": "postgresql://test@ep-prod-pooler.invalid/neondb?sslmode=require",
        "DB_BACKEND": "postgres",
        "SERVER_FALLBACK_KEYS": "0",
        "API_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "LANDING_URL": "https://jarvis.example.test",
        "TRUSTED_PROXY_HOPS": "1",
    }
    assert production_config_errors(env) == []

    env["ALLOWED_CLERK_SUBJECTS"] = "bare-subject"
    assert "ALLOWED_CLERK_SUBJECTS" in production_config_errors(env)
    env["ALLOWED_CLERK_SUBJECTS"] = "clerk:test-user"
    env["TRUSTED_PROXY_HOPS"] = "6"
    env["CORS_ORIGINS"] = "https://jarvis.example.test/path"
    env["DATABASE_URL"] = "postgresql://test@ep-prod-pooler.invalid/neondb"
    env["AUTHORIZED_PARTIES"] = "https://*.example.test"
    errors = production_config_errors(env)
    assert {"TRUSTED_PROXY_HOPS", "CORS_ORIGINS", "DATABASE_URL", "AUTHORIZED_PARTIES"} <= set(errors)
    assert all("test@" not in error for error in errors)


def test_production_config_checker_prints_variable_names_only(monkeypatch, capsys):
    from scripts import check_production_config

    monkeypatch.setenv("JARVIS_SKIP_DOTENV", "1")
    monkeypatch.setenv("JARVIS_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "synthetic-never-print-this")
    assert check_production_config.main() == 1
    output = capsys.readouterr().out
    assert "Invalid or missing: JARVIS_ENV" in output
    assert "synthetic-never-print-this" not in output


def test_cors_and_trusted_proxy_values_are_exact_and_bounded(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://jarvis.example.test/path")
    with pytest.raises(RuntimeError, match="exact origins"):
        configured_cors_origins()

    app = Flask("invalid-proxy-hops-test")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "6")
    with pytest.raises(RuntimeError, match="0 to 5"):
        configure_proxy(app)


def test_production_rejects_missing_or_weak_configuration(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "production")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.delenv("SERVER_FALLBACK_KEYS", raising=False)
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("ALLOWED_CLERK_SUBJECTS", "clerk:test-user")
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("FLASK_SECRET", "weak")
    monkeypatch.setenv("CORS_ORIGINS", "https://jarvis.example.test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example@ep-test-pooler.invalid/neondb?sslmode=require")
    with pytest.raises(RuntimeError, match="FLASK_SECRET"):
        validate_production_config()

    monkeypatch.setenv("FLASK_SECRET", "strong-test-secret-value-0123456789abcdef")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_production_config()

    monkeypatch.setenv("CORS_ORIGINS", "https://jarvis.example.test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_production_config()

    monkeypatch.setenv("DATABASE_URL", "postgresql://example@ep-test-pooler.invalid/neondb?sslmode=require")
    monkeypatch.setenv("AUTH_ENABLED", "0")
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        validate_production_config()

    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example@ep-test-pooler.invalid/neondb?sslmode=require")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example.test")
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example.test/.well-known/jwks.json")
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)
    with pytest.raises(RuntimeError, match="AUTHORIZED_PARTIES"):
        validate_production_config()

    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "http://jarvis.example.test")
    with pytest.raises(RuntimeError, match="AUTHORIZED_PARTIES"):
        validate_production_config()

    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://jarvis.example.test")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example.test")
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example.test/.well-known/jwks.json")
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.delenv("LANDING_URL", raising=False)
    with pytest.raises(RuntimeError, match="LANDING_URL"):
        validate_production_config()
    monkeypatch.setenv("LANDING_URL", "http://localhost:3000")
    with pytest.raises(RuntimeError, match="LANDING_URL"):
        validate_production_config()
    monkeypatch.setenv("LANDING_URL", "https://jarvis.example.test/nested")
    with pytest.raises(RuntimeError, match="LANDING_URL"):
        validate_production_config()
    monkeypatch.setenv("LANDING_URL", "https://[")
    with pytest.raises(RuntimeError, match="LANDING_URL"):
        validate_production_config()
    monkeypatch.setenv("LANDING_URL", "https://jarvis.example.test")
    validate_production_config()


def test_production_requires_postgres_backend(monkeypatch):
    monkeypatch.setenv("JARVIS_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("ALLOWED_CLERK_SUBJECTS", "clerk:test-user")
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("FLASK_SECRET", "strong-test-secret-value-0123456789abcdef")
    monkeypatch.setenv("CORS_ORIGINS", "https://jarvis.example.test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example@ep-test-pooler.invalid/neondb?sslmode=require")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example.test")
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example.test/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://jarvis.example.test")
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("SERVER_FALLBACK_KEYS", "1")
    with pytest.raises(RuntimeError, match="SERVER_FALLBACK_KEYS"):
        validate_production_config()

    monkeypatch.setenv("SERVER_FALLBACK_KEYS", "0")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    with pytest.raises(RuntimeError, match="DB_BACKEND"):
        validate_production_config()
