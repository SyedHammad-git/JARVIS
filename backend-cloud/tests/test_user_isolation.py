"""Owner-isolation coverage for user-visible records and background work."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import pytest
from flask import Flask, g

import app.db as database
import app.memory as memory
import app.monitor as monitor
import app.neural as neural
from app.ai.engine import build_jarvis_context
from app.routes import ai_routes, data_routes, iot_routes, webhook_routes
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
    ],
)
def test_routes_do_not_read_another_owners_rows(isolated_app, path, key, private_value):
    _seed_owner_rows()
    monitor.invalidate_monitor_cache()
    response = isolated_app.test_client().get(path, headers={"X-Test-Owner": "owner-a"})
    assert response.status_code == 200
    assert private_value not in response.get_data(as_text=True)
    assert response.get_json()[key]


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
    assert database.db_scalar(
        "SELECT COUNT(*) FROM notes WHERE owner_username=?", (owner,)
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
    database.db_write(
        "INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES('',?,?,?,?)",
        ("legacy", "legacy", "now", "now"),
    )
    assert assign_legacy_owner.assign_legacy_owner("owner-a", dry_run=True)["notes"] == 1
    assert database.db_scalar("SELECT owner_username FROM notes WHERE title='legacy'") == ""

    assign_legacy_owner.assign_legacy_owner("owner-a")
    assign_legacy_owner.assign_legacy_owner("owner-a")
    assert database.db_scalar("SELECT owner_username FROM notes WHERE title='legacy'") == "owner-a"
    assert database.db_scalar(
        "SELECT owner_username FROM user_owners WHERE owner_username='owner-a'"
    ) == "owner-a"
