"""Owner-isolation coverage for user-visible records and background work."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
import pytest
from flask import Flask, g

import app.db as database
import app.memory as memory
import app.monitor as monitor
import app.neural as neural
from app.ai.engine import build_jarvis_context
from app.routes import ai_routes, data_routes, iot_routes, webhook_routes
from app.routes import key_routes, system_routes
from app.devices import http as device_routes
from app.vision import snapshots


@pytest.fixture
def isolated_app(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "owner-isolation.sqlite")
    monkeypatch.setattr(database, "DB_BACKEND", "sqlite")
    database._sqlite_init()
    app = Flask("owner-isolation")
    app.register_blueprint(data_routes.data)
    app.register_blueprint(iot_routes.iot)
    app.register_blueprint(ai_routes.ai)
    app.register_blueprint(key_routes.keys_bp)
    app.register_blueprint(device_routes.devices_bp)
    app.register_blueprint(system_routes.system)

    @app.before_request
    def authenticate_test_user():
        g.current_user = {"username": request_owner()}

    return app


def request_owner() -> str:
    from flask import request
    return request.headers.get("X-Test-Owner", "owner-a")


def _seed_owner_rows():
    rows = []
    for owner, value in (("owner-a", "private-a"), ("owner-b", "private-b")):
        rows.extend([
            ("INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES(?,?,?,?,?)",
             (owner, value, value, "now", "now")),
            ("INSERT INTO memory_facts(owner_username,category,fact,source,created_at,last_used) VALUES(?,?,?,?,?,?)",
             (owner, "general", value, "test", "now", "now")),
            ("INSERT INTO conversations(owner_username,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
             (owner, "shared", "user", value, "now")),
            ("INSERT INTO alarms(owner_username,time,label,repeat,active,created_at,status) VALUES(?,?,?,?,1,?,'pending')",
             (owner, "09:00", value, "once", "now")),
            ("INSERT INTO monitors(owner_username,name,type,config,status,created_at,active) VALUES(?,?,?,?,'running',?,1)",
             (owner, value, "http", "{}", "now")),
            ("INSERT INTO events(owner_username,type,message,created_at) VALUES(?,?,?,?)",
             (owner, "test", value, "now")),
            ("INSERT INTO command_log(owner_username,command,result,created_at) VALUES(?,?,?,?)",
             (owner, value, "ok", "now")),
              ("INSERT INTO user_api_keys(owner_username,provider,encrypted_key,last4,updated_at) VALUES(?,?,?,?,?)",
               (owner, "groq", f"ciphertext-{owner}", value, "now")),
              ("INSERT INTO devices(device_id,name,token_hash,owner_username,scopes,created_at) VALUES(?,?,?,?,?,?)",
               (f"device-{owner}", value, "0" * 64, owner, "{}", "now")),
            ("INSERT INTO smarthome_devices(owner_username,device_id,name,state,type,icon,room) VALUES(?,?,?,0,'switch','','')",
             (owner, f"switch-{owner}", value)),
        ])
    assert database.db_write_many(rows)
    for owner, value in (("owner-a", "private-a"), ("owner-b", "private-b")):
        monitor_id = database.db_scalar(
            "SELECT id FROM monitors WHERE owner_username=?", (owner,)
        )
        assert database.db_write(
            "INSERT INTO monitor_log(owner_username,monitor_id,monitor_name,result,timestamp) VALUES(?,?,?,?,?)",
            (owner, monitor_id, value, value, "now"),
        )


@pytest.mark.parametrize(
    ("path", "key", "private_value"),
    [
        ("/api/notes", "notes", "private-b"),
        ("/api/memory/facts", "facts", "private-b"),
        ("/api/alarms", "alarms", "private-b"),
        ("/api/db/history?session_id=shared", "history", "private-b"),
        ("/api/db/events", "events", "private-b"),
        ("/api/monitor/list", "monitors", "private-b"),
        ("/api/monitor/log", "log", "private-b"),
        ("/api/keys", "providers", "private-b"),
        ("/api/devices", "devices", "private-b"),
        ("/api/smarthome/devices", "devices", "private-b"),
    ],
)
def test_routes_do_not_read_another_owners_rows(isolated_app, path, key, private_value):
    _seed_owner_rows()
    monitor.invalidate_monitor_cache()
    response = isolated_app.test_client().get(path, headers={"X-Test-Owner": "owner-a"})
    assert response.status_code == 200
    assert private_value not in response.get_data(as_text=True)
    assert response.get_json()[key]


def test_discord_settings_are_isolated_by_owner(isolated_app):
    client = isolated_app.test_client()
    response = client.post(
        "/api/discord/config",
        json={"webhook_url": "https://discord.com/api/webhooks/owner-b/token-b", "enabled": True},
        headers={"X-Test-Owner": "owner-b"},
    )
    assert response.status_code == 200
    assert client.get("/api/discord/config", headers={"X-Test-Owner": "owner-a"}).get_json() == {
        "webhook_configured": False,
        "enabled": False,
    }
    assert client.get("/api/discord/config", headers={"X-Test-Owner": "owner-b"}).get_json() == {
        "webhook_configured": True,
        "enabled": True,
    }


def test_device_status_is_owner_scoped(isolated_app):
    _seed_owner_rows()
    client = isolated_app.test_client()

    owner_a = client.get(
        "/api/device/status?device_id=device-owner-b",
        headers={"X-Test-Owner": "owner-a"},
    )
    owner_b = client.get(
        "/api/device/status?device_id=device-owner-b",
        headers={"X-Test-Owner": "owner-b"},
    )

    assert owner_a.status_code == 404
    assert owner_b.status_code == 200
    assert owner_b.get_json()["device_id"] == "device-owner-b"


def test_user_a_cannot_delete_or_update_user_b_rows(isolated_app):
    _seed_owner_rows()
    client = isolated_app.test_client()
    owner_b = {"X-Test-Owner": "owner-b"}
    alarm_id = database.db_scalar(
        "SELECT id FROM alarms WHERE owner_username=?", ("owner-b",)
    )
    monitor_id = database.db_scalar(
        "SELECT id FROM monitors WHERE owner_username=?", ("owner-b",)
    )
    fact_id = database.db_scalar(
        "SELECT id FROM memory_facts WHERE owner_username=?", ("owner-b",)
    )

    client.post(f"/api/alarms/cancel/{alarm_id}", headers={"X-Test-Owner": "owner-a"})
    client.post("/api/monitor/pause", json={"id": monitor_id}, headers={"X-Test-Owner": "owner-a"})
    client.post("/api/monitor/delete", json={"id": monitor_id}, headers={"X-Test-Owner": "owner-a"})
    client.post("/api/memory/forget", json={"id": fact_id}, headers={"X-Test-Owner": "owner-a"})
    client.post("/api/devices/device-owner-b/revoke", headers={"X-Test-Owner": "owner-a"})
    client.put(
        "/api/devices/device-owner-b/scopes",
        json={"scopes": {"allow_open_app": True}},
        headers={"X-Test-Owner": "owner-a"},
    )
    client.delete("/api/keys/groq", headers={"X-Test-Owner": "owner-a"})
    client.post("/api/smarthome/toggle/switch-owner-b", headers={"X-Test-Owner": "owner-a"})
    client.post("/api/smarthome/remove/switch-owner-b", headers={"X-Test-Owner": "owner-a"})
    client.post(
        "/api/agent/clear", json={"session_id": "shared"},
        headers={"X-Test-Owner": "owner-a"},
    )

    assert database.db_scalar(
        "SELECT active FROM alarms WHERE id=? AND owner_username=?", (alarm_id, "owner-b")
    ) == 1
    assert database.db_scalar(
        "SELECT status FROM monitors WHERE id=? AND owner_username=?", (monitor_id, "owner-b")
    ) == "running"
    assert database.db_scalar(
        "SELECT active FROM monitors WHERE id=? AND owner_username=?", (monitor_id, "owner-b")
    ) == 1
    assert database.db_scalar(
        "SELECT COUNT(*) FROM memory_facts WHERE id=? AND owner_username=?", (fact_id, "owner-b")
    ) == 1
    assert database.db_scalar(
        "SELECT COUNT(*) FROM conversations WHERE session_id='shared' AND owner_username='owner-b'"
    ) == 1
    assert database.db_scalar(
        "SELECT COUNT(*) FROM conversations WHERE session_id='shared' AND owner_username='owner-a'"
    ) == 0
    assert database.db_scalar(
        "SELECT last4 FROM user_api_keys WHERE owner_username=? AND provider='groq'", ("owner-b",)
    ) == "private-b"
    assert database.db_scalar(
        "SELECT revoked FROM devices WHERE device_id='device-owner-b' AND owner_username='owner-b'"
    ) == 0
    assert database.db_scalar(
        "SELECT state FROM smarthome_devices WHERE device_id='switch-owner-b' AND owner_username='owner-b'"
    ) == 0
    assert client.get("/api/db/stats", headers=owner_b).get_json()["command_log"] == 1


def test_memory_search_and_conversation_helpers_filter_owner(isolated_app):
    _seed_owner_rows()
    assert memory.search_facts_semantic("private-b", owner_username="owner-a") == []
    assert memory.load_recent_messages("shared", owner_username="owner-a") == [
        {"role": "user", "content": "private-a"}
    ]
    assert memory.load_recent_messages("shared", owner_username="owner-b") == [
        {"role": "user", "content": "private-b"}
    ]
    context = build_jarvis_context("owner-a")
    assert "private-a" in context
    assert "private-b" not in context


def test_alarm_scheduler_notifies_and_updates_only_its_owner(isolated_app, monkeypatch):
    _seed_owner_rows()
    notifications = []
    monkeypatch.setattr(neural, "groq_as_manager", lambda *_args, **_kwargs: "Reminder")
    monkeypatch.setattr(
        neural, "send_os_notification",
        lambda *args, **kwargs: notifications.append(kwargs.get("owner_username")) or True,
    )
    monkeypatch.setattr(neural, "push_system_event", lambda *_args, **_kwargs: None)
    neural.invalidate_alarm_cache()

    neural.alarm_scheduler_tick(now_time="09:00", owner_username="owner-a")

    assert notifications == ["owner-a"]
    assert database.db_scalar(
        "SELECT active FROM alarms WHERE owner_username='owner-a'"
    ) == 0
    assert database.db_scalar(
        "SELECT active FROM alarms WHERE owner_username='owner-b'"
    ) == 1


def test_background_cache_keys_include_owner(isolated_app):
    _seed_owner_rows()
    neural.invalidate_alarm_cache()
    monitor.invalidate_monitor_cache()
    neural.refresh_alarm_cache("owner-a", force=True)
    neural.refresh_alarm_cache("owner-b", force=True)
    monitor.refresh_monitor_cache("owner-a", force=True)
    monitor.refresh_monitor_cache("owner-b", force=True)

    assert set(neural._alarm_cache) >= {"owner-a", "owner-b"}
    assert set(monitor._monitor_cache) >= {"owner-a", "owner-b"}
    assert neural._alarm_cache["owner-a"][0]["label"] == "private-a"
    assert monitor._monitor_cache["owner-b"][0]["name"] == "private-b"


def test_heartbeat_state_and_notifications_are_owner_keyed(monkeypatch):
    notifications = []
    neural.register_heartbeat_owner("heartbeat-a")
    neural.register_heartbeat_owner("heartbeat-b")
    neural.update_heartbeat_config("heartbeat-a", {"coding_break_mins": 1})
    neural.update_heartbeat_config("heartbeat-b", {"enabled": False})
    with neural.heartbeat_lock:
        neural._heartbeat_states["heartbeat-a"]["session"]["start"] = time.time() - 3600
        neural._heartbeat_states["heartbeat-b"]["session"]["start"] = time.time() - 3600
    monkeypatch.setattr(
        neural, "send_os_notification",
        lambda *args, **kwargs: notifications.append(kwargs.get("owner_username")) or True,
    )

    neural.heartbeat_scan("heartbeat-a")

    assert notifications == ["heartbeat-a"]
    assert len(neural.get_heartbeat_queue("heartbeat-a")) == 1
    assert neural.get_heartbeat_queue("heartbeat-b") == []


def test_snapshot_files_are_partitioned_and_owner_purge_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    image = b"\xff\xd8\xfftest"
    assert snapshots.save_snapshot("img_a", image, owner_username="owner-a")
    assert snapshots.save_snapshot("img_b", image, owner_username="owner-b")

    snapshots.purge_owner_snapshots("owner-a")

    assert not list(tmp_path.rglob("img_a.jpg"))
    assert list(tmp_path.rglob("img_b.jpg"))


def test_clerk_user_deleted_webhook_verifies_svix_and_purges_owner(
    isolated_app, monkeypatch, tmp_path
):
    _seed_owner_rows()
    owner = "clerk:deleted-subject"
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    assert database.db_write_many([
        ("INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES(?,?,?,?,?)",
         (owner, "delete", "delete", "now", "now")),
        ("INSERT INTO conversations(owner_username,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
         (owner, "session", "user", "delete", "now")),
        ("INSERT INTO alarms(owner_username,time,label,repeat,active,created_at) VALUES(?,?,?,?,1,?)",
         (owner, "09:00", "delete", "once", "now")),
        ("INSERT INTO memory_facts(owner_username,category,fact,created_at) VALUES(?,?,?,?)",
         (owner, "general", "delete", "now")),
        ("INSERT INTO monitors(owner_username,name,created_at) VALUES(?,?,?)",
         (owner, "delete", "now")),
        ("INSERT INTO monitor_log(owner_username,monitor_name,result,timestamp) VALUES(?,?,?,?)",
         (owner, "delete", "delete", "now")),
        ("INSERT INTO command_log(owner_username,command,created_at) VALUES(?,?,?)",
         (owner, "delete", "now")),
        ("INSERT INTO events(owner_username,type,message,created_at) VALUES(?,?,?,?)",
         (owner, "test", "delete", "now")),
        ("INSERT INTO heartbeat_log(owner_username,trigger,message,created_at) VALUES(?,?,?,?)",
         (owner, "test", "delete", "now")),
        ("INSERT INTO session_stats(owner_username,date) VALUES(?,?)",
         (owner, "today")),
        ("INSERT INTO cameras(owner_username,name) VALUES(?,?)",
         (owner, "delete")),
        ("INSERT INTO smarthome_devices(owner_username,device_id,name) VALUES(?,?,?)",
         (owner, "delete-device", "delete")),
        ("INSERT INTO discord_settings(owner_username,webhook_url,enabled,updated_at) VALUES(?,?,1,?)",
         (owner, "https://discord.com/api/webhooks/example/placeholder", "now")),
        ("INSERT INTO user_owners(owner_username) VALUES(?)", (owner,)),
        ("INSERT INTO devices(device_id,name,token_hash,owner_username,created_at) VALUES(?,?,?,?,?)",
         ("dev-delete", "test", "0" * 64, owner, "now")),
        ("INSERT INTO user_api_keys(owner_username,provider,encrypted_key,updated_at) VALUES(?,?,?,?)",
         (owner, "groq", "encrypted-test-value", "now")),
        ("INSERT INTO pairing_codes(code_hash,owner_username,name,expires_at) VALUES(?,?,?,?)",
         ("hash-test", owner, "test", time.time() + 100)),
        ("INSERT INTO pending_confirmations(owner_username,session_id,nonce_hash,message,tool_signature,expires_at) "
         "VALUES(?,?,?,?,?,?)",
         (owner, "session", "nonce", "message", "tool", time.time() + 100)),
    ])
    assert snapshots.save_snapshot("img_delete", b"\xff\xd8\xff", owner_username=owner)
    assert snapshots.save_snapshot("img_keep", b"\xff\xd8\xff", owner_username="clerk:other")
    secret_bytes = b"unit-test-webhook-secret"
    monkeypatch.setenv(
        "CLERK_WEBHOOK_SECRET",
        "whsec_" + base64.b64encode(secret_bytes).decode("ascii"),
    )
    raw = json.dumps(
        {"type": "user.deleted", "data": {"id": "deleted-subject"}},
        separators=(",", ":"),
    ).encode()
    message_id = "evt_test_delete"
    timestamp = str(int(time.time()))
    signed = message_id.encode() + b"." + timestamp.encode() + b"." + raw
    signature = base64.b64encode(
        hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    ).decode("ascii")
    app = Flask("clerk-webhook-test")
    app.register_blueprint(webhook_routes.webhooks)

    response = app.test_client().post(
        "/api/webhooks/clerk",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "svix-id": message_id,
            "svix-timestamp": timestamp,
            "svix-signature": f"v1,{signature}",
        },
    )

    assert response.status_code == 200
    for table in database.SQLITE_OWNER_SCOPED_TABLES:
        assert database.db_scalar(
            f"SELECT COUNT(*) FROM {table} WHERE owner_username=?", (owner,)
        ) == 0
    assert database.db_scalar(
        "SELECT COUNT(*) FROM conversations WHERE owner_username='owner-a'"
    ) == 1
    for table in (
        "devices", "user_api_keys", "pairing_codes", "pending_confirmations", "user_owners",
    ):
        assert database.db_scalar(
            f"SELECT COUNT(*) FROM {table} WHERE owner_username=?", (owner,)
        ) == 0
    assert not list((tmp_path / "snapshots").rglob("img_delete.jpg"))
    assert list((tmp_path / "snapshots").rglob("img_keep.jpg"))


def test_clerk_webhook_rejects_invalid_signature(isolated_app, monkeypatch):
    owner = "clerk:keep-subject"
    database.db_write(
        "INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES(?,?,?,?,?)",
        (owner, "keep", "keep", "now", "now"),
    )
    monkeypatch.setenv("CLERK_WEBHOOK_SECRET", "whsec_" + base64.b64encode(b"secret").decode())
    payload = {"type": "user.deleted", "data": {"id": "keep-subject"}}
    app = Flask("clerk-webhook-invalid")
    app.register_blueprint(webhook_routes.webhooks)

    response = app.test_client().post(
        "/api/webhooks/clerk",
        json=payload,
        headers={
            "svix-id": "evt_invalid",
            "svix-timestamp": str(int(time.time())),
            "svix-signature": "v1,invalid",
        },
    )

    assert response.status_code == 401
    assert database.db_scalar(
        "SELECT COUNT(*) FROM notes WHERE owner_username=?", (owner,)
    ) == 1


def test_legacy_owner_assignment_dry_run_and_repeat_are_safe(isolated_app, monkeypatch, tmp_path):
    from scripts import assign_legacy_owner

    monkeypatch.setattr(assign_legacy_owner, "SNAPSHOT_DIR", tmp_path / "snapshots")
    database.cfg_set(
        "smarthome_devices",
        json.dumps({"legacy_light": {"name": "Legacy light", "state": True, "type": "light"}}),
    )
    database.cfg_set("discord_webhook_url", "https://discord.com/api/webhooks/example/placeholder")
    database.cfg_set("discord_enabled", "true")
    database.db_write(
        "INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES('',?,?,?,?)",
        ("legacy", "legacy", "now", "now"),
    )
    dry_run_counts = assign_legacy_owner.assign_legacy_owner("owner-a", dry_run=True)
    assert dry_run_counts["notes"] == 1
    assert dry_run_counts["legacy_smarthome_devices"] == 1
    assert database.db_scalar("SELECT owner_username FROM notes WHERE title='legacy'") == ""
    assert json.loads(database.cfg_get("smarthome_devices"))["legacy_light"]["name"] == "Legacy light"
    assert database.cfg_get("discord_webhook_url") == "https://discord.com/api/webhooks/example/placeholder"

    assign_legacy_owner.assign_legacy_owner("owner-a")
    assign_legacy_owner.assign_legacy_owner("owner-a")
    assert database.db_scalar("SELECT owner_username FROM notes WHERE title='legacy'") == "owner-a"
    assert database.db_scalar(
        "SELECT owner_username FROM user_owners WHERE owner_username='owner-a'"
    ) == "owner-a"
    assert set(assign_legacy_owner._OWNER_TABLES) == set(database.SQLITE_OWNER_SCOPED_TABLES)
    assert database.cfg_get("smarthome_devices") == ""
    assert database.cfg_get("discord_webhook_url") == ""
    assert database.cfg_get("discord_enabled") == ""
    assert database.db_scalar(
        "SELECT COUNT(*) FROM discord_settings WHERE owner_username='owner-a'"
    ) == 0
    assert database.db_scalar(
        "SELECT name FROM smarthome_devices WHERE owner_username='owner-a' AND device_id='legacy_light'"
    ) == "Legacy light"
    assert database.db_scalar(
        "SELECT COUNT(*) FROM smarthome_devices WHERE owner_username='owner-b' AND device_id='legacy_light'"
    ) == 0


@pytest.mark.parametrize("table", ["user_api_keys", "pairing_codes", "pending_confirmations"])
def test_sqlite_migrates_owner_column_on_existing_scoped_tables(table, monkeypatch, tmp_path):
    database_path = tmp_path / "legacy-owner.sqlite"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    legacy_schemas = {
        "user_api_keys": "CREATE TABLE user_api_keys (provider TEXT PRIMARY KEY, encrypted_key TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "pairing_codes": "CREATE TABLE pairing_codes (code_hash TEXT PRIMARY KEY, name TEXT NOT NULL, expires_at REAL NOT NULL)",
        "pending_confirmations": "CREATE TABLE pending_confirmations (session_id TEXT PRIMARY KEY, nonce_hash TEXT NOT NULL, message TEXT NOT NULL, tool_signature TEXT NOT NULL, expires_at REAL NOT NULL)",
    }
    with sqlite3.connect(database_path) as connection:
        connection.execute(legacy_schemas[table])

    database._sqlite_init()

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    assert "owner_username" in columns


@pytest.mark.parametrize("table", database.SQLITE_OWNER_SCOPED_TABLES)
def test_scoped_table_crud_cannot_cross_owner_boundary(isolated_app, table):
    cases = {
        "conversations": (
            "INSERT INTO conversations(owner_username,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
            lambda owner, value: (owner, "shared", "user", value, "now"), "id", "content",
        ),
        "notes": (
            "INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES(?,?,?,?,?)",
            lambda owner, value: (owner, value, value, "now", "now"), "id", "title",
        ),
        "alarms": (
            "INSERT INTO alarms(owner_username,time,label,repeat,active,created_at) VALUES(?,?,?,?,1,?)",
            lambda owner, value: (owner, "09:00", value, "once", "now"), "id", "label",
        ),
        "command_log": (
            "INSERT INTO command_log(owner_username,command,created_at) VALUES(?,?,?)",
            lambda owner, value: (owner, value, "now"), "id", "command",
        ),
        "events": (
            "INSERT INTO events(owner_username,type,message,created_at) VALUES(?,?,?,?)",
            lambda owner, value: (owner, "test", value, "now"), "id", "message",
        ),
        "memory_facts": (
            "INSERT INTO memory_facts(owner_username,category,fact,created_at) VALUES(?,?,?,?)",
            lambda owner, value: (owner, "general", value, "now"), "id", "fact",
        ),
        "monitors": (
            "INSERT INTO monitors(owner_username,name,created_at) VALUES(?,?,?)",
            lambda owner, value: (owner, value, "now"), "id", "name",
        ),
        "monitor_log": (
            "INSERT INTO monitor_log(owner_username,monitor_name,result,timestamp) VALUES(?,?,?,?)",
            lambda owner, value: (owner, value, value, "now"), "id", "monitor_name",
        ),
        "heartbeat_log": (
            'INSERT INTO heartbeat_log(owner_username,"trigger",message,created_at) VALUES(?,?,?,?)',
            lambda owner, value: (owner, value, value, "now"), "id", "message",
        ),
        "session_stats": (
            "INSERT INTO session_stats(owner_username,date) VALUES(?,?)",
            lambda owner, value: (owner, value), "id", "date",
        ),
        "cameras": (
            "INSERT INTO cameras(owner_username,name) VALUES(?,?)",
            lambda owner, value: (owner, value), "id", "name",
        ),
        "devices": (
            "INSERT INTO devices(device_id,name,token_hash,owner_username,created_at) VALUES(?,?,?,?,?)",
            lambda owner, value: (f"device-{owner}", value, "0" * 64, owner, "now"), "device_id", "name",
        ),
        "user_api_keys": (
            "INSERT INTO user_api_keys(owner_username,provider,encrypted_key,updated_at) VALUES(?,?,?,?)",
            lambda owner, value: (owner, "groq", value, "now"), "provider", "encrypted_key",
        ),
        "pairing_codes": (
            "INSERT INTO pairing_codes(code_hash,owner_username,name,expires_at) VALUES(?,?,?,?)",
            lambda owner, value: (f"hash-{owner}", owner, value, time.time() + 60), "code_hash", "name",
        ),
        "pending_confirmations": (
            "INSERT INTO pending_confirmations(owner_username,session_id,nonce_hash,message,tool_signature,expires_at) VALUES(?,?,?,?,?,?)",
            lambda owner, value: (owner, "shared", value, value, value, time.time() + 60), "session_id", "message",
        ),
        "smarthome_devices": (
            "INSERT INTO smarthome_devices(owner_username,device_id,name,state,type,icon,room) VALUES(?,?,?,0,'switch','','')",
            lambda owner, value: (owner, f"switch-{owner}", value), "device_id", "name",
        ),
        "discord_settings": (
            "INSERT INTO discord_settings(owner_username,webhook_url,enabled,updated_at) VALUES(?,?,1,?)",
            lambda owner, value: (owner, value, "now"), "owner_username", "webhook_url",
        ),
    }
    insert_sql, make_values, primary_key, marker = cases[table]
    identifiers = {}
    for owner, value in (("owner-a", "private-a"), ("owner-b", "private-b")):
        assert database.db_write(insert_sql, make_values(owner, value))
        row = database.db_read(
            f"SELECT {primary_key} FROM {table} WHERE owner_username=?", (owner,)
        )[-1]
        identifiers[owner] = row[primary_key]

    owner_a_rows = database.db_read(
        f"SELECT {marker} FROM {table} WHERE owner_username=?", ("owner-a",)
    )
    assert [row[marker] for row in owner_a_rows] == ["private-a"]
    assert database.db_write(
        f"UPDATE {table} SET {marker}=? WHERE {primary_key}=? AND owner_username=?",
        ("updated-a", identifiers["owner-a"], "owner-a"),
    )
    assert database.db_write(
        f"DELETE FROM {table} WHERE {primary_key}=? AND owner_username=?",
        (identifiers["owner-a"], "owner-a"),
    )
    assert database.db_scalar(
        f"SELECT {marker} FROM {table} WHERE {primary_key}=? AND owner_username=?",
        (identifiers["owner-b"], "owner-b"),
    ) == "private-b"
