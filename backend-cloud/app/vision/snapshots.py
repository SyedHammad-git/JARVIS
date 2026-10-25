"""On-demand device snapshots, bounded before vision and conversation history."""
from __future__ import annotations

import base64
import binascii
import datetime
import secrets
import threading
import time
import hashlib
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
    owner_username: str | None = None,
) -> None:
    active_backend = (backend or database.DB_BACKEND).lower()
    if active_backend == "postgres":
        current_time = time.time() if now is None else now
        expires_before = datetime.datetime.fromtimestamp(current_time, datetime.timezone.utc)
        owners = (
            [owner_username] if owner_username is not None else [
                row["owner_username"] for row in database.db_read(
                    "SELECT owner_username FROM user_owners ORDER BY owner_username"
                )
            ]
        )
        for owner in owners:
            database.db_write(
                "DELETE FROM snapshots WHERE owner_username=? AND expires_at <= ?",
                (owner, expires_before),
            )
        return

    directory = Path(image_dir or SNAPSHOT_DIR)
    if not directory.is_dir():
        return
    current_time = time.time() if now is None else now
    if image_dir is None:
        if owner_username is None:
            owners = [
                row["owner_username"] for row in database.db_read(
                    "SELECT owner_username FROM user_owners ORDER BY owner_username"
                )
            ]
        else:
            owners = [owner_username]
        directories = [
            directory / hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]
            for owner in owners
        ]
    else:
        directories = [directory]
    try:
        for owner_directory in directories:
            for image_path in owner_directory.rglob("img_*.jpg"):
                if current_time - image_path.stat().st_mtime >= SNAPSHOT_TTL_SECONDS:
                    image_path.unlink(missing_ok=True)
    except OSError:
        pass


def save_snapshot(
    snapshot_id: str,
    image_bytes: bytes,
    image_dir: Path | None = None,
    backend: str | None = None,
    owner_username: str = "",
) -> bool:
    active_backend = (backend or database.DB_BACKEND).lower()
    cleanup_snapshots(
        image_dir=image_dir,
        backend=active_backend,
        owner_username=owner_username,
    )
    if active_backend == "postgres":
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            seconds=SNAPSHOT_TTL_SECONDS
        )
        return database.db_write(
            "INSERT INTO snapshots(snapshot_id,owner_username,image,expires_at) VALUES(?,?,?,?)",
            (snapshot_id, owner_username, image_bytes, expires_at),
        )

    directory = Path(image_dir or SNAPSHOT_DIR)
    try:
        if owner_username:
            owner_dir = hashlib.sha256(owner_username.encode("utf-8")).hexdigest()[:24]
            snapshot_path = directory / owner_dir / f"{snapshot_id}.jpg"
        else:
            snapshot_path = directory / f"{snapshot_id}.jpg"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(image_bytes)
        return True
    except OSError:
        return False


def purge_owner_snapshots(owner_username: str) -> None:
    if database.DB_BACKEND == "postgres":
        database.db_write("DELETE FROM snapshots WHERE owner_username=?", (owner_username,))
        return
    owner_dir = hashlib.sha256(owner_username.encode("utf-8")).hexdigest()[:24]
    directory = SNAPSHOT_DIR / owner_dir
    if not directory.is_dir():
        return
    for image_path in directory.glob("img_*.jpg"):
        image_path.unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass


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


def snapshot_ack_to_text(
    ack: dict,
    question: str,
    image_dir: Path | None = None,
    vision_fn=None,
    owner_username: str = "",
) -> str:
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
    if not save_snapshot(
        snapshot_id, image_bytes, image_dir=image_dir, owner_username=owner_username
    ):
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
