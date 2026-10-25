"""On-demand device snapshots, bounded before vision and conversation history."""
from __future__ import annotations

import base64
import binascii
import datetime
import secrets
import threading
import time
from collections import deque
from pathlib import Path

import app.db as database
from app.db import DATA_DIR

MAX_IMAGE_BYTES = 1024 * 1024
SNAPSHOT_TTL_SECONDS = 24 * 60 * 60
SNAPSHOT_DIR = DATA_DIR / "snapshots"


def cleanup_snapshots(
    image_dir: Path | None = None,
    now: float | None = None,
    backend: str | None = None,
) -> None:
    active_backend = (backend or database.DB_BACKEND).lower()
    if active_backend == "postgres":
        current_time = time.time() if now is None else now
        expires_before = datetime.datetime.fromtimestamp(current_time, datetime.timezone.utc)
        database.db_write("DELETE FROM snapshots WHERE expires_at <= ?", (expires_before,))
        return

    directory = Path(image_dir or SNAPSHOT_DIR)
    if not directory.is_dir():
        return
    current_time = time.time() if now is None else now
    try:
        for image_path in directory.glob("img_*.jpg"):
            if current_time - image_path.stat().st_mtime >= SNAPSHOT_TTL_SECONDS:
                image_path.unlink(missing_ok=True)
    except OSError:
        pass


def save_snapshot(
    snapshot_id: str,
    image_bytes: bytes,
    image_dir: Path | None = None,
    backend: str | None = None,
) -> bool:
    active_backend = (backend or database.DB_BACKEND).lower()
    cleanup_snapshots(image_dir=image_dir, backend=active_backend)
    if active_backend == "postgres":
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            seconds=SNAPSHOT_TTL_SECONDS
        )
        return database.db_write(
            "INSERT INTO snapshots(snapshot_id,image,expires_at) VALUES(?,?,?)",
            (snapshot_id, image_bytes, expires_at),
        )

    directory = Path(image_dir or SNAPSHOT_DIR)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{snapshot_id}.jpg").write_bytes(image_bytes)
        return True
    except OSError:
        return False


class SnapshotRateLimiter:
    def __init__(self, limit: int = 6, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.lock = threading.Lock()
        self.requests: dict[str, deque[float]] = {}

    def allow(self, user_key: str) -> bool:
        key = str(user_key or "unknown")[:200]
        now = self.clock()
        with self.lock:
            for known_user, known_attempts in tuple(self.requests.items()):
                while known_attempts and now - known_attempts[0] >= self.window_seconds:
                    known_attempts.popleft()
                if not known_attempts:
                    del self.requests[known_user]
            attempts = self.requests.setdefault(key, deque())
            if len(attempts) >= self.limit:
                return False
            attempts.append(now)
            return True


snapshot_rate_limiter = SnapshotRateLimiter()


def snapshot_ack_to_text(ack: dict, question: str, image_dir: Path | None = None, vision_fn=None) -> str:
    if not isinstance(ack, dict):
        return "Camera snapshot failed."
    if ack.get("ok") is False:
        error = ack.get("error")
        return f"Camera snapshot failed: {error}." if isinstance(error, str) else "Camera snapshot failed."

    image_b64 = ack.get("image_b64")
    if not isinstance(image_b64, str) or ack.get("mime") != "image/jpeg":
        return "Camera snapshot rejected: invalid image response."
    max_encoded_length = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
    if len(image_b64) > max_encoded_length:
        return "Camera snapshot rejected: image exceeds 1 MiB."
    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        return "Camera snapshot rejected: invalid image encoding."
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return "Camera snapshot rejected: image exceeds 1 MiB."
    if not image_bytes.startswith(b"\xff\xd8\xff"):
        return "Camera snapshot rejected: invalid JPEG image."

    snapshot_id = f"img_{secrets.token_urlsafe(9)}"
    if not save_snapshot(snapshot_id, image_bytes, image_dir=image_dir):
        return "Camera snapshot could not be stored."

    if vision_fn is None:
        from app.ai.engine import call_gemini
        vision_fn = call_gemini
    safe_question = question.strip()[:500] if isinstance(question, str) else ""
    prompt = (
        "Describe this camera snapshot concisely. Do not infer identities. "
        f"User question: {safe_question or 'What is visible?'}"
    )
    try:
        result = vision_fn(prompt, image_base64=image_b64)
        description = result.get("text", "") if isinstance(result, dict) and result.get("ok") else ""
    except Exception:
        description = ""
    description = " ".join(description.split())[:500] if isinstance(description, str) else ""
    summary = f"Snapshot saved as {snapshot_id}."
    return f"{summary} {description}" if description else f"{summary} Image description unavailable."
