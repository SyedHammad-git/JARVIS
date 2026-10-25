from __future__ import annotations

import hashlib
import os
import pkgutil
import subprocess
import sys
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
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://dashboard.example.test")
    monkeypatch.delenv("SERVER_FALLBACK_KEYS", raising=False)
    for provider_key in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY"):
        monkeypatch.setenv(provider_key, "")
    monkeypatch.setattr(
        security,
        "_verify_clerk_token",
        lambda token: f"clerk:{subject}" if token == "valid-token" else None,
    )
    app = create_app(testing=True)
    return app, app.test_client()


def _headers(token="valid-token"):
    return {"Authorization": f"Bearer {token}"}


def test_user_key_is_encrypted_and_scoped_by_clerk_subject(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    response = client.post("/api/keys/groq", json={"key": "provider-secret-1234"}, headers=_headers())
    assert response.status_code == 200

    stored = db.db_read(
        "SELECT encrypted_key FROM user_api_keys WHERE owner_username=?",
        ("clerk:clerk_user_1",),
    )
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
    assert groq == {
        "provider": "groq",
        "configured": True,
        "last4": "1234",
        "status": "saved",
        "last_tested_at": "",
    }
    assert "provider-secret-1234" not in listed.get_data(as_text=True)

    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "clerk:another_clerk_user")
    other_user = client.get("/api/keys", headers=_headers())
    other_groq = next(provider for provider in other_user.get_json()["providers"] if provider["provider"] == "groq")
    assert other_groq["configured"] is False


def test_missing_key_error_and_one_time_pair_code(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    for env_name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY"):
        monkeypatch.delenv(env_name, raising=False)
    missing = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert missing.status_code == 400
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
    assert replay.status_code == 400
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
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", origin)
    security._clerk_jwks_clients.clear()

    class FakeJwksClient:
        def __init__(self, _url, *, cache_keys, lifespan, timeout):
            assert cache_keys is True
            assert lifespan == 3600
            assert timeout == 5

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

    assert db.db_write(
        "INSERT OR REPLACE INTO users(username,password_hash,totp_secret,created_at,disabled) "
        "VALUES(?,?,?,?,0)",
        ("clerk_user", "hash", "totp-seed", "now"),
    )
    assert security._verify_clerk_token(token_for(origin)) == "clerk:clerk_user"
    assert security._verify_clerk_token(token_for(origin)) != "clerk_user"
    assert security._verify_clerk_token(token_for("https://other.example.test")) is None


def test_clerk_invalid_tokens_return_401(monkeypatch, tmp_path):
    issuer = "https://clerk.example.test"
    origin = "https://dashboard.example.test"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    real_verifier = security._verify_clerk_token
    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("CLERK_ISSUER", issuer)
    monkeypatch.setenv("CLERK_JWKS_URL", f"{issuer}/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", origin)
    security._clerk_jwks_clients.clear()

    class FakeJwksClient:
        def __init__(self, _url, **kwargs):
            assert kwargs == {"cache_keys": True, "lifespan": 3600, "timeout": 5}

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=private_key.public_key())

    monkeypatch.setattr(jwt, "PyJWKClient", FakeJwksClient)
    monkeypatch.setattr(security, "_verify_clerk_token", real_verifier)

    now = int(time.time())

    def token_for(claims, algorithm="RS256", key=private_key):
        return jwt.encode(claims, key, algorithm=algorithm)

    base = {"sub": "user-1", "iss": issuer, "azp": origin, "iat": now, "exp": now + 60}
    valid = token_for(base)
    assert client.get("/api/keys", headers=_headers(valid)).status_code == 200

    invalid_tokens = [
        token_for({**base, "exp": now - 90}),
        token_for({**base, "iss": "https://wrong-issuer.example.test"}),
        token_for({**base, "azp": "https://wrong-origin.example.test"}),
        token_for({**base, "sub": None}),
        jwt.encode({**base, "sub": "user-1"}, key="", algorithm="none"),
        token_for(base, algorithm="HS256", key="hmac-key-for-algorithm-confusion-test-32-bytes"),
        token_for({key: value for key, value in base.items() if key != "sub"}),
    ]
    for token in invalid_tokens:
        response = client.get("/api/keys", headers=_headers(token))
        assert response.status_code == 401
        assert response.get_json()["error"] == "authentication_required"


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
    assert db.db_read(
        "SELECT provider FROM user_api_keys WHERE owner_username=?",
        ("clerk:clerk_user_1",),
    ) == []


def test_stored_key_test_updates_status_without_exposing_key(monkeypatch, tmp_path, caplog):
    _app, client = _client(monkeypatch, tmp_path)
    key = "saved-provider-key-9876"
    assert client.post(
        "/api/keys/groq",
        json={"key": key},
        headers=_headers(),
    ).status_code == 200
    from app.routes import key_routes

    class ProviderResponse:
        status_code = 200

    monkeypatch.setattr(
        key_routes.requests,
        "get",
        lambda *_args, **_kwargs: ProviderResponse(),
    )
    tested = client.post(
        "/api/keys/groq/test",
        json={"key": key},
        headers=_headers(),
    )
    assert tested.status_code == 200
    status = next(
        entry for entry in client.get("/api/keys", headers=_headers()).get_json()["providers"]
        if entry["provider"] == "groq"
    )
    assert status["status"] == "valid"
    assert status["last_tested_at"]
    assert key not in tested.get_data(as_text=True)
    assert key not in caplog.text


def test_authenticated_users_never_fall_back_to_server_keys(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    for provider_key in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY"):
        monkeypatch.setenv(provider_key, f"server-only-{provider_key}")
    from app.routes import ai_routes

    seen = []

    def fake_agent(*_args, **_kwargs):
        seen.append(get_api_key("GROQ_KEY"))
        return {"ok": True, "reply": "ready", "steps": [], "iterations": 0, "model": "test"}

    monkeypatch.setattr(ai_routes, "run_agent", fake_agent)
    missing = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert missing.status_code == 400
    assert missing.get_json() == {"ok": False, "error": "no_api_key"}
    assert seen == []
    from app import config

    original_environment = config.os.environ

    class ProviderEnvReadGuard(dict):
        def get(self, name, default=None):
            if name in {"GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY"}:
                raise AssertionError("authenticated empty-key context accessed server provider environment")
            return super().get(name, default)

    context_token = config.set_user_api_keys({})
    monkeypatch.setattr(config.os, "environ", ProviderEnvReadGuard(dict(original_environment)))
    try:
        assert config.get_api_key("GROQ_KEY") == ""
    finally:
        config.reset_user_api_keys(context_token)
        monkeypatch.setattr(config.os, "environ", original_environment)

    saved = client.post(
        "/api/keys/groq",
        json={"key": "owned-user-key"},
        headers=_headers(),
    )
    assert saved.status_code == 200
    chat = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert chat.status_code == 200
    assert seen == ["owned-user-key"]

    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "clerk:user-b")
    other_user = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert other_user.status_code == 400
    assert other_user.get_json()["error"] == "no_api_key"
    assert seen == ["owned-user-key"]


def test_server_key_fallback_requires_explicit_opt_in(monkeypatch, caplog):
    from app import config

    monkeypatch.setattr(config, "_server_fallback_warning_logged", False)
    context_token = config.set_user_api_keys({})
    monkeypatch.setenv("SERVER_FALLBACK_KEYS", "1")
    monkeypatch.setenv("GROQ_KEY", "server-fallback-test-value")
    try:
        assert config.get_api_key("GROQ_KEY") == "server-fallback-test-value"
    finally:
        config.reset_user_api_keys(context_token)
    assert "SERVER_FALLBACK_KEYS=1" in caplog.text
    assert "server-fallback-test-value" not in caplog.text


def test_background_context_cannot_use_server_keys_in_multi_user_mode(monkeypatch):
    from app import config

    monkeypatch.setenv("JARVIS_ENV", "production")
    monkeypatch.delenv("SERVER_FALLBACK_KEYS", raising=False)
    monkeypatch.setenv("GROQ_KEY", "background-server-key")
    assert config.get_api_key("GROQ_KEY") == ""


def test_key_decryption_is_lazy_and_rotation_is_supported(monkeypatch, tmp_path, caplog):
    _app, client = _client(monkeypatch, tmp_path)
    owner = "clerk:clerk_user_1"
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", old_key)
    from app import key_store

    key_store.save_user_key(owner, "groq", "rotation-test-key")
    original = db.db_read(
        "SELECT encrypted_key FROM user_api_keys WHERE owner_username=? AND provider=?",
        (owner, "groq"),
    )[0]["encrypted_key"]

    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY_OLD", old_key)
    assert key_store.load_user_keys(owner) == {"GROQ_KEY": "rotation-test-key"}
    assert key_store.rotate_user_keys(dry_run=True) == 1
    assert db.db_read(
        "SELECT encrypted_key FROM user_api_keys WHERE owner_username=? AND provider=?",
        (owner, "groq"),
    )[0]["encrypted_key"] == original
    assert key_store.rotate_user_keys() == 1
    rotated = db.db_read(
        "SELECT encrypted_key,key_version FROM user_api_keys WHERE owner_username=? AND provider=?",
        (owner, "groq"),
    )[0]
    assert rotated["encrypted_key"] != original
    assert int(rotated["key_version"]) == 2
    assert Fernet(new_key.encode("ascii")).decrypt(rotated["encrypted_key"].encode("ascii")) == b"rotation-test-key"
    monkeypatch.delenv("API_KEY_ENCRYPTION_KEY_OLD")
    assert key_store.load_user_keys(owner) == {"GROQ_KEY": "rotation-test-key"}

    monkeypatch.setattr(
        key_store,
        "_fernet",
        lambda: (_ for _ in ()).throw(AssertionError("decryption attempted on devices route")),
    )
    devices = client.get("/api/devices", headers=_headers())
    assert devices.status_code == 200
    assert "rotation-test-key" not in devices.get_data(as_text=True)
    assert "rotation-test-key" not in caplog.text


def test_key_decryption_errors_are_sanitized(monkeypatch, tmp_path, caplog):
    _app, client = _client(monkeypatch, tmp_path)
    assert client.post(
        "/api/keys/groq",
        json={"key": "never-log-this-provider-key"},
        headers=_headers(),
    ).status_code == 200
    assert db.db_write(
        "UPDATE user_api_keys SET encrypted_key=? WHERE owner_username=? AND provider=?",
        ("malformed-ciphertext", "clerk:clerk_user_1", "groq"),
    )
    response = client.post("/api/agent", json={"message": "hello"}, headers=_headers())
    assert response.status_code == 503
    assert response.get_json() == {"ok": False, "error": "api_key_storage_unavailable"}
    assert "never-log-this-provider-key" not in response.get_data(as_text=True)
    assert "never-log-this-provider-key" not in caplog.text


def test_failover_uses_only_configured_user_providers(monkeypatch):
    from app import config
    from app.ai import engine

    monkeypatch.setenv("GROQ_KEY", "server-groq-key")
    monkeypatch.setenv("GEMINI_KEY", "server-gemini-key")
    monkeypatch.setenv("OPENROUTER_KEY", "server-openrouter-key")
    context_token = config.set_user_api_keys({"OPENROUTER_KEY": "user-openrouter-key"})
    attempted = []
    monkeypatch.setattr(engine, "call_groq", lambda *_args, **_kwargs: attempted.append("groq"))
    monkeypatch.setattr(engine, "call_openrouter", lambda *_args, **_kwargs: attempted.append(
        ("openrouter", config.get_api_key("OPENROUTER_KEY"))
    ) or {"ok": False, "error": "unavailable"})
    monkeypatch.setattr(engine, "call_gemini", lambda *_args, **_kwargs: attempted.append("gemini"))
    try:
        engine.route_ai_call([{"role": "user", "content": "hello"}])
    finally:
        config.reset_user_api_keys(context_token)
    assert attempted == [("openrouter", "user-openrouter-key")]


def test_pair_code_brute_force_rate_limits_and_uniform_errors(monkeypatch, tmp_path):
    _app, client = _client(monkeypatch, tmp_path)
    from app import db
    from app.devices import http as device_http
    from app.devices.pairing import create_pair_code

    device_http._PAIR_GLOBAL_LIMIT = 120
    for _ in range(5):
        response = client.post(
            "/pairing/redeem-code",
            json={"code": "ABCDEFGH"},
            environ_overrides={"REMOTE_ADDR": "198.51.100.1"},
        )
        assert response.status_code == 400
        assert response.get_json() == {"ok": False, "error": "pair_code_invalid"}
    locked = client.post(
        "/pairing/redeem-code",
        json={"code": "ABCDEFGH"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.1"},
    )
    assert locked.status_code == 429

    unknown = client.post(
        "/pairing/redeem-code",
        json={"code": "JKLMNPQR"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.2"},
    )
    pair_code, expiry = create_pair_code("clerk:clerk_user_1")
    assert all(char in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for char in pair_code)
    assert expiry > time.time()
    db.db_write(
        "UPDATE pairing_codes SET expires_at=? WHERE code_hash=?",
        (time.time() - 1, hashlib.sha256(pair_code.encode()).hexdigest()),
    )
    expired = client.post(
        "/pairing/redeem-code",
        json={"code": pair_code},
        environ_overrides={"REMOTE_ADDR": "198.51.100.3"},
    )
    assert unknown.status_code == expired.status_code == 400
    assert unknown.get_json() == expired.get_json() == {"ok": False, "error": "pair_code_invalid"}

    assert db.db_write("DELETE FROM pair_code_rate_limits")
    device_http._PAIR_GLOBAL_LIMIT = 3
    global_responses = [
        client.post(
            "/pairing/redeem-code",
            json={"code": "ABCDEFGH"},
            environ_overrides={"REMOTE_ADDR": f"198.51.100.{index}"},
        )
        for index in range(4, 8)
    ]
    assert [response.status_code for response in global_responses] == [400, 400, 400, 429]


def test_every_app_module_imports_in_a_fresh_interpreter():
    import app as app_package

    modules = [app_package.__name__]
    modules.extend(
        module.name
        for module in pkgutil.walk_packages(app_package.__path__, app_package.__name__ + ".")
    )
    env = os.environ.copy()
    env["JARVIS_SKIP_DOTENV"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for module in modules:
        result = subprocess.run(
            [sys.executable, "-c", f"import importlib; importlib.import_module({module!r})"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, f"fresh import failed for {module}: {result.stderr[-1500:]}"


def test_legacy_clerk_owners_are_migrated_without_local_user_collision(monkeypatch, tmp_path):
    _app, _client_instance = _client(monkeypatch, tmp_path)
    assert db.db_write(
        "INSERT INTO users(username,password_hash,totp_secret,created_at,disabled) "
        "VALUES(?,?,?,?,0)",
        ("local-user", "hash", "totp-seed", "now"),
    )
    for device_id, owner in (
        ("dev-legacy-clerk", "legacy-clerk-sub"),
        ("dev-local-user", "local-user"),
    ):
        assert db.db_write(
            "INSERT INTO devices(device_id,name,token_hash,owner_username,scopes,revoked,created_at,last_seen) "
            "VALUES(?,?,?,?,?,0,?,?)",
            (device_id, device_id, "0" * 64, owner, "{}", "now", ""),
        )
    assert db.db_write(
        "INSERT INTO user_api_keys(owner_username,provider,encrypted_key,updated_at) VALUES(?,?,?,?)",
        ("legacy-clerk-sub", "groq", "encrypted", "now"),
    )
    assert db.db_write(
        "INSERT INTO pairing_codes(code_hash,owner_username,name,expires_at) VALUES(?,?,?,?)",
        ("code-hash", "legacy-clerk-sub", "PC", time.time() + 60),
    )

    db._sqlite_init()
    owners = {
        row["device_id"]: row["owner_username"]
        for row in db.db_read("SELECT device_id,owner_username FROM devices")
    }
    assert owners["dev-legacy-clerk"] == "clerk:legacy-clerk-sub"
    assert owners["dev-local-user"] == "local-user"
    assert db.db_read("SELECT owner_username FROM user_api_keys")[0]["owner_username"] == "clerk:legacy-clerk-sub"
    assert db.db_read("SELECT owner_username FROM pairing_codes")[0]["owner_username"] == "clerk:legacy-clerk-sub"


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

    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "clerk:another_clerk_user")
    from app.key_store import save_user_key

    save_user_key("clerk:another_clerk_user", "groq", "other-user-key")
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
    monkeypatch.setattr(security, "_verify_clerk_token", lambda _token: "clerk:clerk_user_1")

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
    assert expired.status_code == 400
