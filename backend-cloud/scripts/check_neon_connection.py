"""Probe the pooled Neon URL and report only a connection class."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_backend_environment() -> None:
    if os.environ.get("JARVIS_SKIP_DOTENV") == "1":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


def classify_connection_error(error: Exception) -> str:
    detail = str(error).lower()
    if "channel_binding" in detail or "channel binding" in detail:
        return "channel_binding"
    if any(marker in detail for marker in ("password authentication", "authentication failed", "invalid password")):
        return "auth"
    return "network"


def main() -> int:
    load_backend_environment()
    connection_url = os.environ.get("DATABASE_URL", "").strip()
    if not connection_url:
        print("DATABASE_URL=EMPTY")
        return 2
    print("DATABASE_URL=set (value suppressed)")

    try:
        import psycopg2
        from psycopg2.extensions import libpq_version

        parsed = urlsplit(connection_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["connect_timeout"] = "5"
        safe_timeout_url = urlunsplit(parsed._replace(query=urlencode(query)))
        connection = psycopg2.connect(safe_timeout_url)
        connection.close()
        print(f"LIBPQ_VERSION={libpq_version()}")
        print("POOL_CONNECTION=OK")
        return 0
    except Exception as exc:
        try:
            version = psycopg2.extensions.libpq_version()
            print(f"LIBPQ_VERSION={version}")
        except Exception:
            pass
        result = classify_connection_error(exc)
        print(f"POOL_CONNECTION={result}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
