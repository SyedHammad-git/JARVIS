"""Assign unscoped legacy user data to OWNER_USERNAME."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_backend_environment() -> None:
    if os.environ.get("JARVIS_SKIP_DOTENV") == "1":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


load_backend_environment()

from app import db as database
from app.db import OWNER_SCOPED_TABLES
from app.smarthome import import_legacy_devices
from app.vision.snapshots import SNAPSHOT_DIR

_OWNER_TABLES = tuple(
    table for table in OWNER_SCOPED_TABLES if table not in {"snapshots", "memory_vectors"}
)


def assign_legacy_owner(owner_username: str, *, dry_run: bool = False) -> dict[str, int]:
    if not dry_run:
        database.register_owner(owner_username)
    tables = list(_OWNER_TABLES)
    if database.DB_BACKEND == "postgres":
        tables.extend(("memory_vectors", "snapshots"))
    counts = {}
    for table in tables:
        counts[table] = int(database.db_scalar(
            f"SELECT COUNT(*) FROM {table} WHERE owner_username='' OR owner_username IS NULL"
        ) or 0)
        if counts[table] and not dry_run:
            if not database.db_write(
                f"UPDATE {table} SET owner_username=? WHERE owner_username='' OR owner_username IS NULL",
                (owner_username,),
            ):
                raise RuntimeError(f"Could not assign legacy rows in {table}")

    legacy_discord_settings = int(database.db_scalar(
        "SELECT COUNT(*) FROM config WHERE key IN (?,?)",
        ("discord_webhook_url", "discord_enabled"),
    ) or 0)
    counts["legacy_discord_settings"] = legacy_discord_settings
    if legacy_discord_settings and not dry_run:
        if not database.db_write(
            "DELETE FROM config WHERE key IN (?,?)",
            ("discord_webhook_url", "discord_enabled"),
        ):
            raise RuntimeError("Could not remove shared legacy Discord settings")

    legacy_smart_home = database.cfg_get("smarthome_devices", "")
    try:
        legacy_smart_home_devices = json.loads(legacy_smart_home) if legacy_smart_home else {}
    except (TypeError, json.JSONDecodeError):
        legacy_smart_home_devices = {}
    counts["legacy_smarthome_devices"] = (
        len(legacy_smart_home_devices) if isinstance(legacy_smart_home_devices, dict) else 0
    )
    if legacy_smart_home and not dry_run:
        import_legacy_devices(owner_username, legacy_smart_home)
        if not database.db_write("DELETE FROM config WHERE key=?", ("smarthome_devices",)):
            raise RuntimeError("Could not remove shared legacy smart-home configuration")

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
