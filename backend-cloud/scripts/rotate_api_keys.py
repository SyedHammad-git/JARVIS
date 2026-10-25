"""Re-encrypt provider keys with API_KEY_ENCRYPTION_KEY."""
from __future__ import annotations

import argparse

from app import load_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count stored keys without changing encrypted values",
    )
    args = parser.parse_args()
    load_environment()
    from app.db import init_db
    from app.key_store import rotate_user_keys

    init_db()
    count = rotate_user_keys(dry_run=args.dry_run)
    verb = "would be rotated" if args.dry_run else "rotated"
    print(f"{count} provider key(s) {verb}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
