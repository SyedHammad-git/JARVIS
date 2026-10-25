from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

from app import create_app
from app import db
from app import security
from app.config import get_api_key


def _client(monkeypatch, tmp_path, subject="clerk_user_1"):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(db, "DB_BACKEND", "sqlite")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example.test")
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example.test/.well-known/jwks.json")
    for provider_key in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY"):
        monkeypatch.setenv(provider_key, "")
    monkeypatch.setattr(security, "_verify_clerk_token", lambda token: subject if token == "valid-token" else None)
    app = create_app(testing=True)
    return app, app.test_client()


def _headers(token="valid-token"):
    return {"Authorization": f"Bearer {token}"}


def test_user_key_is_encrypted_and_scoped_by_clerk_subject(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    response = client.post("/api/keys/groq", json={"key": "provider-secret-1234"}, headers=_headers())
    assert response.status_code == 200

    stored = db.db_read("SELECT encrypted_key FROM user_api_keys WHERE owner_username=?", ("clerk_user_1",))
    assert stored
    assert "provider-secret-1234" not in stored[0]["encrypted_key"]
    from app.routes import ai_routes

    observed_keys = []

    def fake_agent(*_args, **_kwargs):
        observed_keys.append(get_api_key("GROQ_KEY"))
        return {"ok": True, "reply": "ready", "steps": [], "iterations": 0, "model": "test"}

    monkeypatch.setattr(ai_routes, "run_agent", fake_agent)
    chat = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert chat.status_code == 200
    assert observed_keys == ["provider-secret-1234"]

    listed = client.get("/api/keys", headers=_headers())
    assert listed.status_code == 200
    groq = next(provider for provider in listed.get_json()["providers"] if provider["provider"] == "groq")
    assert groq == {"provider": "groq", "configured": True, "last4": "1234"}
    assert "provider-secret-1234" not in listed.get_data(as_text=True)

    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "another_clerk_user")
    other_user = client.get("/api/keys", headers=_headers())
    other_groq = next(provider for provider in other_user.get_json()["providers"] if provider["provider"] == "groq")
    assert other_groq["configured"] is False


def test_missing_key_error_and_one_time_pair_code(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    for env_name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY"):
        monkeypatch.delenv(env_name, raising=False)
    missing = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert missing.status_code == 428
    assert missing.get_json()["error"] == "no_api_key"

    issued = client.post("/api/devices/pair-code", json={"name": "Laptop"}, headers=_headers())
    assert issued.status_code == 200
    code = issued.get_json()["code"]
    assert len(code) == 8
    assert issued.get_json()["expires_in"] == 600

    redeemed = client.post("/pairing/redeem-code", json={"code": code})
    assert redeemed.status_code == 200
    assert redeemed.headers["Cache-Control"] == "no-store"
    payload = redeemed.get_json()
    assert payload["name"] == "Laptop"
    assert payload["device_id"]
    assert payload["token"]

    replay = client.post("/pairing/redeem-code", json={"code": code})
    assert replay.status_code == 404
    devices = client.get("/api/devices", headers=_headers())
    assert devices.status_code == 200
    assert devices.get_json()["devices"][0]["name"] == "Laptop"


def test_bearer_token_failure_is_rejected(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    response = client.get("/api/keys", headers=_headers("invalid-token"))
    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_required"


def test_clerk_jwt_signature_issuer_and_authorized_party(monkeypatch):
    issuer = "https://clerk.example.test"
    origin = "https://dashboard.example.test"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("CLERK_ISSUER", issuer)
    monkeypatch.setenv("CLERK_JWKS_URL", f"{issuer}/.well-known/jwks.json")
    monkeypatch.setenv("CORS_ORIGINS", origin)
    security._clerk_jwks_clients.clear()

    class FakeJwksClient:
        def __init__(self, _url, cache_keys):
            assert cache_keys is True

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=private_key.public_key())

    monkeypatch.setattr(jwt, "PyJWKClient", FakeJwksClient)

    def token_for(authorized_party):
        now = int(time.time())
        return jwt.encode(
            {
                "sub": "clerk_user",
                "iss": issuer,
                "azp": authorized_party,
                "iat": now,
                "exp": now + 60,
            },
            private_key,
            algorithm="RS256",
        )

    assert security._verify_clerk_token(token_for(origin)) == "clerk_user"
    assert security._verify_clerk_token(token_for("https://other.example.test")) is None


def test_provider_key_test_uses_supplied_key_without_persisting(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    from app.routes import key_routes

    calls = []

    class ProviderResponse:
        status_code = 200

    def fake_get(url, *, headers, params, timeout):
        calls.append((url, headers, params, timeout))
        return ProviderResponse()

    monkeypatch.setattr(key_routes.requests, "get", fake_get)
    response = client.post(
        "/api/keys/groq/test",
        json={"key": "temporary-test-key"},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "valid": True}
    assert calls[0][1] == {"Authorization": "Bearer temporary-test-key"}
    assert calls[0][3] == 8
    assert db.db_read("SELECT provider FROM user_api_keys WHERE owner_username=?", ("clerk_user_1",)) == []


def test_agent_confirmation_is_user_scoped_and_one_time(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    client.post("/api/keys/groq", json={"key": "temporary-provider-key"}, headers=_headers())
    from app.routes import ai_routes

    observed_contexts = []

    def fake_agent(_message, **kwargs):
        observed_contexts.append(kwargs["ctx"])
        if not kwargs["ctx"]["confirmed"]:
            return {
                "ok": True,
                "reply": "Approval is required.",
                "needs_confirmation": True,
                "tool": "open_app",
                "args": {"app": "notepad"},
                "reason": "high_risk",
            }
        return {"ok": True, "reply": "Action complete.", "steps": [], "iterations": 1, "model": "test"}

    monkeypatch.setattr(ai_routes, "run_agent", fake_agent)
    initial = client.post(
        "/api/agent",
        json={"message": "Open Notepad", "session_id": "dashboard"},
        headers=_headers(),
    )
    assert initial.status_code == 200
    payload = initial.get_json()
    assert payload["needs_confirmation"] is True
    nonce = payload["confirmation_nonce"]
    assert nonce

    monkeypatch.setenv("GROQ_KEY", "test-placeholder-key")
    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "another_clerk_user")
    other_user = client.post(
        "/api/agent",
        json={
            "message": "Open Notepad",
            "session_id": "dashboard",
            "confirmed": True,
            "confirmation_nonce": nonce,
        },
        headers=_headers(),
    )
    assert other_user.status_code == 403
    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "clerk_user_1")

    confirmed = client.post(
        "/api/agent",
        json={
            "message": "Open Notepad",
            "session_id": "dashboard",
            "confirmed": True,
            "confirmation_nonce": nonce,
        },
        headers=_headers(),
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["reply"] == "Action complete."
    assert observed_contexts[1]["confirmed_signature"] == ai_routes.tool_confirmation_signature(
        "open_app", {"app": "notepad"}
    )

    replay = client.post(
        "/api/agent",
        json={
            "message": "Open Notepad",
            "session_id": "dashboard",
            "confirmed": True,
            "confirmation_nonce": nonce,
        },
        headers=_headers(),
    )
    assert replay.status_code == 403


def test_pair_code_expiry_is_enforced(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    issued = client.post("/api/devices/pair-code", json={}, headers=_headers())
    code = issued.get_json()["code"]
    assert db.db_write("UPDATE pairing_codes SET expires_at=? WHERE code_hash=?", (0, hashlib.sha256(code.encode()).hexdigest()))
    expired = client.post("/pairing/redeem-code", json={"code": code})
    assert expired.status_code == 404
