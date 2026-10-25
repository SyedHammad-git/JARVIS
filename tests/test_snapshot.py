"""On-demand snapshots never leak encoded image bytes into agent history."""
import base64
import json
import logging
from unittest.mock import patch

import tools  # noqa: F401
import agent
from tools.device_tools import tool_take_snapshot
import config
import database
from vision import snapshots
from vision.snapshots import (
    MAX_IMAGE_BYTES,
    SnapshotRateLimiter,
    cleanup_snapshots,
    save_snapshot,
    snapshot_ack_to_text,
)


def test_oversized_snapshot_is_rejected_before_vision_or_storage(tmp_path, caplog):
    image_b64 = base64.b64encode(b"\xff\xd8\xff" + b"x" * MAX_IMAGE_BYTES).decode("ascii")
    vision = patch("ai_engine.call_gemini")
    with vision as call_vision, caplog.at_level(logging.INFO):
        result = snapshot_ack_to_text(
            {"image_b64": image_b64, "mime": "image/jpeg"},
            "describe it",
            image_dir=tmp_path,
        )

    assert result == "Camera snapshot rejected: image exceeds 1 MiB."
    call_vision.assert_not_called()
    assert not list(tmp_path.iterdir())
    assert image_b64 not in caplog.text


def test_snapshot_sends_image_only_to_vision_and_keeps_it_out_of_history(tmp_path, caplog, monkeypatch):
    image_bytes = b"\xff\xd8\xffsmall-jpeg-payload"
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    user_key = "snapshot-test-user-redaction"
    chats = []

    def fake_chat(messages, tools=None, **kwargs):
        chats.append(json.dumps(messages, sort_keys=True))
        if len(chats) == 1:
            return {
                "ok": True,
                "model": "test",
                "tool_calls": [{
                    "id": "snapshot-call",
                    "name": "take_snapshot",
                    "args": {"question": "What is visible?"},
                }],
                "raw_assistant_message": {"role": "assistant", "content": None},
            }
        return {
            "ok": True,
            "model": "test",
            "text": "A desk is visible.",
            "tool_calls": [],
            "raw_assistant_message": {"role": "assistant", "content": "A desk is visible."},
        }

    saved = []
    def save_message(*args):
        saved.append(json.dumps(args))
        return True

    with patch("agent.chat", side_effect=fake_chat), \
         patch("devices.gateway.call_device", return_value={"image_b64": image_b64, "mime": "image/jpeg"}) as call_device, \
         patch("ai_engine.call_gemini", return_value={"ok": True, "text": "A desk is visible."}) as call_vision, \
         patch("agent.load_recent_messages", return_value=[]), \
         patch("agent.save_message", side_effect=save_message), \
         patch("agent.prune_conversation", return_value=True), \
         caplog.at_level(logging.INFO):
        result = agent.run_agent(
            "Take a snapshot and describe it.",
            session_id="snapshot-redaction-test",
            ctx={
                "execution_mode": "remote",
                "device_online": True,
                "device_id": "dev_snapshot_test",
                "snapshot_user": user_key,
            },
        )

    assert result["ok"]
    assert image_b64 not in json.dumps(chats)
    assert image_b64 not in json.dumps(saved)
    assert image_b64 not in caplog.text
    assert image_b64 not in json.dumps(result)
    assert "Snapshot saved as img_" in result["steps"][0]["result"]
    assert __import__("re").search(r"Snapshot saved as img_[A-Za-z0-9_-]+\.", result["steps"][0]["result"])
    assert "A desk is visible." in result["steps"][0]["result"]
    call_device.assert_called_once()
    assert call_device.call_args.kwargs["timeout"] == 20
    assert call_vision.call_args.kwargs["image_base64"] == image_b64
    stored_images = list(tmp_path.glob("img_*.jpg"))
    assert len(stored_images) == 1
    assert stored_images[0].read_bytes() == image_bytes


def test_snapshot_rate_limiter_is_per_user_and_six_per_minute():
    instant = [100.0]
    limiter = SnapshotRateLimiter(clock=lambda: instant[0])
    assert all(limiter.allow("user-a") for _ in range(6))
    assert not limiter.allow("user-a")
    assert limiter.allow("user-b")
    instant[0] += 60
    assert limiter.allow("user-a")


def test_opencv_snapshot_helper_refuses_remote_mode(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_MODE", "remote")
    monkeypatch.setattr(config, "CV2_OK", True)
    assert tool_take_snapshot({}) == {"ok": False, "error": "camera_unavailable"}


def test_snapshot_cleanup_removes_expired_files_only(tmp_path):
    expired = tmp_path / "img_expired.jpg"
    recent = tmp_path / "img_recent.jpg"
    unrelated = tmp_path / "notes.txt"
    for image in (expired, recent, unrelated):
        image.write_bytes(b"x")
    expired_time = 100
    recent_time = 200
    import os
    os.utime(expired, (expired_time, expired_time))
    os.utime(recent, (recent_time, recent_time))

    cleanup_snapshots(tmp_path, now=recent_time + 24 * 60 * 60 - 1)

    assert not expired.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_neon_snapshot_storage_uses_bytea_expiry_and_db_cleanup(monkeypatch):
    writes = []
    monkeypatch.setattr(database, "DB_BACKEND", "postgres")
    monkeypatch.setattr(database, "db_write", lambda sql, params=(): writes.append((sql, params)) or True)
    image = b"\xff\xd8\xffsnapshot"

    assert save_snapshot("img_test", image, backend="postgres")
    assert writes[0][0] == "DELETE FROM snapshots WHERE expires_at <= ?"
    assert writes[1][0] == "INSERT INTO snapshots(snapshot_id,image,expires_at) VALUES(?,?,?)"
    assert writes[1][1][0:2] == ("img_test", image)
    assert writes[1][1][2].tzinfo is not None