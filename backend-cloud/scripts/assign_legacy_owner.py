"""Assign unscoped legacy user data to OWNER_USERNAME."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

os.environ["JARVIS_SKIP_DOTENV"] = "1"

from app import db as database
from app.vision.snapshots import SNAPSHOT_DIR

_OWNER_TABLES = (
    "conversations", "notes", "alarms", "memory_facts", "monitors",
    "monitor_log", "command_log", "events", "heartbeat_log", "session_stats", "cameras",
)


def assign_legacy_owner(owner_username: str, *, dry_run: bool = False) -> dict[str, int]:
    tables = list(_OWNER_TABLES)
    if database.DB_BACKEND == "postgres":
        tables.extend(("memory_vectors", "snapshots"))
    counts = {}
    for table in tables:
        counts[table] = int(database.db_scalar(
            f"SELECT COUNT(*) FROM {table} WHERE owner_username=''"
        ) or 0)
        if counts[table] and not dry_run:
            if not database.db_write(
                f"UPDATE {table} SET owner_username=? WHERE owner_username=''",
                (owner_username,),
            ):
                raise RuntimeError(f"Could not assign legacy rows in {table}")

    if database.DB_BACKEND == "sqlite":
        legacy_images = list(SNAPSHOT_DIR.glob("img_*.jpg"))
        counts["snapshot_files"] = len(legacy_images)
        if legacy_images and not dry_run:
            owner_dir = hashlib.sha256(owner_username.encode("utf-8")).hexdigest()[:24]
            target_dir = SNAPSHOT_DIR / owner_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            for image in legacy_images:
                destination = target_dir / image.name
                if destination.exists():
                    raise FileExistsError(f"Legacy snapshot destination already exists: {destination.name}")
                image.replace(destination)
    if not dry_run:
        database.register_owner(owner_username)
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    owner_username = os.environ.get("OWNER_USERNAME", "").strip()
    if not owner_username:
        print("OWNER_USERNAME is required.")
        return 2
    database.init_db()
    counts = assign_legacy_owner(owner_username, dry_run=args.dry_run)
    for table, count in counts.items():
        print(f"{table}: {count} unassigned row(s)")
    print("Dry run: no rows changed." if args.dry_run else "Legacy ownership assignment completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
