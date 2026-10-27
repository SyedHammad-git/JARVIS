"""Validate production environment variable names/shapes without printing values."""
from __future__ import annotations

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


def main() -> int:
    load_backend_environment()
    from app.security import production_config_errors

    errors = production_config_errors()
    if errors:
        print("Production config: FAIL")
        for name in errors:
            print(f"Invalid or missing: {name}")
        return 1
    print("Production config: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
