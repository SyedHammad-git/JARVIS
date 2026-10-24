"""
╔══════════════════════════════════════════════════════════════════════════╗
║  J.A.R.V.I.S v17.M — Database Abstraction Layer                        ║
║  FIXED:                                                                  ║
║    BUG-4  Unified column names: created_at everywhere (SQLite=Supabase) ║
║    BUG-8  cfg_set PG: updated → updated_at (Supabase config schema)     ║
║    POOL   PostgreSQL ThreadedConnectionPool (no new conn per query)     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from pathlib import Path
from threading import Lock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("jarvis.db")

HOME     : Path = Path(os.path.expanduser("~"))
DATA_DIR : Path = HOME / "JARVIS_Data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH  : Path = DATA_DIR / "jarvis.db"

DB_BACKEND: str = os.environ.get("DB_BACKEND", "sqlite").lower().strip()

# ════════════════════════════════════════════════════════════════════
# SCHEMA — unified column names matching Supabase production schema
# All timestamps use created_at / updated_at
# ════════════════════════════════════════════════════════════════════
_SCHEMA: str = """
-- Chat history
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL DEFAULT 'default',
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    tools_used  TEXT    DEFAULT '',
    ai_model    TEXT    DEFAULT 'groq'
);

-- Notes
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Alarms / reminders
CREATE TABLE IF NOT EXISTS alarms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    time         TEXT    NOT NULL,
    label        TEXT    NOT NULL DEFAULT 'Reminder',
    repeat       TEXT    NOT NULL DEFAULT 'once',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL,
    trigger_time TEXT    DEFAULT '',
    status       TEXT    DEFAULT 'pending',
    retry_count  INTEGER DEFAULT 0
);

-- Command audit log
CREATE TABLE IF NOT EXISTS command_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    command    TEXT    NOT NULL,
    result     TEXT    DEFAULT '',
    blocked    INTEGER DEFAULT 0,
    remote     INTEGER DEFAULT 0,
    created_at TEXT    NOT NULL
);

-- System events
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Persistent key-value config
CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Long-term memory facts
CREATE TABLE IF NOT EXISTS memory_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT    NOT NULL DEFAULT 'general',
    fact       TEXT    NOT NULL,
    source     TEXT    DEFAULT 'learned',
    created_at TEXT    NOT NULL,
    last_used  TEXT    DEFAULT ''
);

-- Heartbeat / proactive message log
CREATE TABLE IF NOT EXISTS heartbeat_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger    TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    priority   TEXT    DEFAULT 'medium',
    delivered  INTEGER DEFAULT 0,
    created_at TEXT    NOT NULL
);

-- Work-session statistics
CREATE TABLE IF NOT EXISTS session_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT    NOT NULL,
    active_minutes  INTEGER DEFAULT 0,
    commands_given  INTEGER DEFAULT 0,
    ai_calls        INTEGER DEFAULT 0,
    break_reminders INTEGER DEFAULT 0,
    last_active     TEXT    DEFAULT ''
);

-- Cameras
CREATE TABLE IF NOT EXISTS cameras (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT    NOT NULL DEFAULT 'Camera',
    source TEXT    NOT NULL DEFAULT '0',
    active INTEGER NOT NULL DEFAULT 0
);

-- Monitors (url/timeout stored in config JSON)
CREATE TABLE IF NOT EXISTS monitors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    type          TEXT    NOT NULL DEFAULT 'http',
    config        TEXT    NOT NULL DEFAULT '{}',
    status        TEXT    NOT NULL DEFAULT 'running',
    created_at    TEXT    NOT NULL,
    last_check    TEXT    DEFAULT '',
    trigger_count INTEGER DEFAULT 0,
    active        INTEGER DEFAULT 1,
    paused_at     TEXT    DEFAULT ''
);

-- Monitor per-check log
CREATE TABLE IF NOT EXISTS monitor_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id   INTEGER,
    monitor_name TEXT    DEFAULT '',
    result       TEXT    DEFAULT '',
    alert_sent   INTEGER DEFAULT 0,
    timestamp    TEXT    NOT NULL
);
"""

db_lock: Lock = Lock()

# ════════════════════════════════════════════════════════════════════
# SQLITE BACKEND
# ════════════════════════════════════════════════════════════════════
def _sqlite_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _sqlite_init() -> None:
    with db_lock:
        conn = _sqlite_connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            log.info("SQLite ready: %s", DB_PATH)
            print(f"[DB] ✅ SQLite ready: {DB_PATH}")
        finally:
            conn.close()


def _sqlite_write(sql: str, params: tuple = ()) -> bool:
    with db_lock:
        conn = _sqlite_connect()
        try:
            conn.execute(sql, params)
            conn.commit()
            return True
        except Exception as exc:
            log.error("sqlite_write | SQL: %s | err: %s", sql[:120], exc)
            try:
                conn.rollback()
            except Exception:
                pass   # connection may already be unusable — commit/rollback both no-ops then
            return False
        finally:
            conn.close()


def _sqlite_read(sql: str, params: tuple = ()) -> list[dict]:
    conn = _sqlite_connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        log.error("sqlite_read | SQL: %s | err: %s", sql[:120], exc)
        return []
    finally:
        conn.close()


def _sqlite_scalar(sql: str, params: tuple = ()):
    conn = _sqlite_connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    except Exception as exc:
        log.error("sqlite_scalar | SQL: %s | err: %s", sql[:120], exc)
        return None
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════
# POSTGRESQL BACKEND  (psycopg2 + ThreadedConnectionPool)
# ════════════════════════════════════════════════════════════════════
_pg_pool      = None
_pg_pool_lock = Lock()


def _pg_dsn() -> str:
    dsn = os.environ.get("POSTGRES_DSN", "").strip()
    if not dsn:
        raise EnvironmentError(
            "[DB] POSTGRES_DSN not set in .env\n"
            "  Add: POSTGRES_DSN=postgresql://user:pass@host:5432/dbname"
        )
    return dsn


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is None:
            try:
                import psycopg2.pool
            except ImportError:
                raise ImportError("[DB] psycopg2 not installed — run: pip install psycopg2-binary")
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(2, 10, _pg_dsn())
            log.info("PostgreSQL connection pool created (min=2, max=10)")
    return _pg_pool


def _pg_placeholder(sql: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL %s."""
    return sql.replace("?", "%s")


def _postgres_init() -> None:
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public';"
            )
            count = cur.fetchone()[0]
        conn.commit()
        print(f"[DB] ✅ PostgreSQL ready — Supabase connected ({count} tables found)")
        log.info("PostgreSQL ready — %d tables", count)
    except Exception as exc:
        print(f"[DB] ❌ PostgreSQL connection FAILED: {exc}")
        log.error("PostgreSQL init failed: %s", exc)
        raise
    finally:
        pool.putconn(conn)


def _postgres_write(sql: str, params: tuple = ()) -> bool:
    pg_sql = _pg_placeholder(sql)
    pool   = _get_pg_pool()
    conn   = None
    try:
        with db_lock:
            conn = pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(pg_sql, params if params else None)
                conn.commit()
                return True
            except Exception as exc:
                conn.rollback()
                log.error("pg_write | SQL: %s | err: %s", pg_sql[:120], exc)
                print(f"[DB PG WRITE ERROR]: {exc}\n  SQL: {pg_sql[:80]}")
                return False
            finally:
                pool.putconn(conn)
    except Exception as exc:
        log.error("pg_write pool error: %s", exc)
        return False


def _postgres_read(sql: str, params: tuple = ()) -> list[dict]:
    pg_sql = _pg_placeholder(sql)
    pool   = _get_pg_pool()
    conn   = None
    try:
        import psycopg2.extras
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(pg_sql, params if params else None)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            log.error("pg_read | SQL: %s | err: %s", pg_sql[:120], exc)
            return []
        finally:
            pool.putconn(conn)
    except Exception as exc:
        log.error("pg_read pool error: %s", exc)
        return []


def _postgres_scalar(sql: str, params: tuple = ()):
    rows = _postgres_read(sql, params)
    return list(rows[0].values())[0] if rows else None


# ════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════
def init_db() -> None:
    global DB_BACKEND
    if DB_BACKEND == "sqlite":
        _sqlite_init()
    elif DB_BACKEND == "postgres":
        try:
            _postgres_init()
        except Exception as exc:
            print(f"[DB] ⚠ PostgreSQL failed ({exc.__class__.__name__}: {exc})")
            print("[DB] ↩ Falling back to SQLite — check Supabase project is not paused")
            print("[DB]   Go to: https://supabase.com/dashboard → your project → Resume")
            DB_BACKEND = "sqlite"
            _sqlite_init()
    else:
        raise ValueError(f"[DB] Unknown DB_BACKEND='{DB_BACKEND}'. Use: sqlite | postgres")


def db_write(sql: str, params: tuple = ()) -> bool:
    if DB_BACKEND == "sqlite":    return _sqlite_write(sql, params)
    if DB_BACKEND == "postgres":  return _postgres_write(sql, params)
    raise NotImplementedError(f"db_write: unknown backend {DB_BACKEND}")


def db_read(sql: str, params: tuple = ()) -> list[dict]:
    if DB_BACKEND == "sqlite":    return _sqlite_read(sql, params)
    if DB_BACKEND == "postgres":  return _postgres_read(sql, params)
    raise NotImplementedError(f"db_read: unknown backend {DB_BACKEND}")


def db_scalar(sql: str, params: tuple = ()):
    if DB_BACKEND == "sqlite":    return _sqlite_scalar(sql, params)
    if DB_BACKEND == "postgres":  return _postgres_scalar(sql, params)
    raise NotImplementedError(f"db_scalar: unknown backend {DB_BACKEND}")


def cfg_get(key: str, default: str = "") -> str:
    rows = db_read("SELECT value FROM config WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def cfg_set(key: str, value) -> None:
    now = datetime.datetime.now().isoformat()
    if DB_BACKEND == "sqlite":
        # SQLite uses updated_at (schema above)
        db_write(
            "INSERT OR REPLACE INTO config(key,value,updated_at) VALUES(?,?,?)",
            (key, str(value), now),
        )
    elif DB_BACKEND == "postgres":
        # ✅ BUG-8 FIX: Supabase config table uses updated_at
        _postgres_write(
            """
            INSERT INTO config(key, value, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
            """,
            (key, str(value), now),
        )


def ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


init_db()
