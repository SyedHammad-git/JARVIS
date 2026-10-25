"""
╔══════════════════════════════════════════════════════════════════════════╗
║  J.A.R.V.I.S v17.M — Database Abstraction Layer                        ║
║  FIXED:                                                                  ║
║    BUG-4  Unified column names: created_at everywhere                   ║
║    BUG-8  cfg_set PG: updated → updated_at                              ║
║    POOL   PostgreSQL ThreadedConnectionPool (no new conn per query)     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
SQLITE_FALLBACK_ACTIVE = False
PG_RECOVERY_INTERVAL_SECONDS = 300

# ════════════════════════════════════════════════════════════════════
# SCHEMA — shared logical schema; SQLite and Postgres use converted forms
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

-- Paired Electron / fake devices (token stored as sha256 hex only)
CREATE TABLE IF NOT EXISTS devices (
    device_id  TEXT PRIMARY KEY,
    name       TEXT    NOT NULL DEFAULT 'PC',
    token_hash TEXT    NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    last_seen  TEXT    DEFAULT ''
);
"""


def postgres_schema_from_sqlite(schema: str = _SCHEMA) -> str:
    converted = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        schema,
        flags=re.IGNORECASE,
    )
    return re.sub(r"(?m)^([ \t]*)trigger([ \t]+TEXT\b)", r'\1"trigger"\2', converted, flags=re.IGNORECASE)


_POSTGRES_SCHEMA = postgres_schema_from_sqlite()
_POSTGRES_SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    image BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_expires_at_idx ON snapshots(expires_at);
"""
_POSTGRES_VECTOR_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS memory_vectors (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_vectors_embedding_hnsw_idx
    ON memory_vectors USING hnsw (embedding vector_cosine_ops);
"""


def _postgres_url(variable: str = "DATABASE_URL") -> str:
    connection_url = os.environ.get(variable, "").strip()
    if not connection_url:
        raise EnvironmentError(f"{variable} is not set")
    parsed = urlsplit(connection_url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
        raise ValueError(f"{variable} must be a PostgreSQL URL")
    is_pooler = "-pooler" in parsed.hostname.lower()
    if variable == "DATABASE_URL" and not is_pooler:
        raise ValueError("DATABASE_URL must use the Neon pooled endpoint")
    if variable == "DATABASE_URL_DIRECT" and is_pooler:
        raise ValueError("DATABASE_URL_DIRECT must use the direct endpoint")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["sslmode"] = "require"
    return urlunsplit(parsed._replace(query=urlencode(query)))

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


# ── columns that MUST exist per table (name, sql_type, default_expr) ────────
# Only the columns that legacy DBs are known to be missing are listed here.
# New columns added to _SCHEMA later should be added here too.
# SQLite ADD COLUMN only allows a constant default (not datetime()).
# Empty/zero defaults are backfilled immediately after ALTER below.
_REQUIRED_COLUMNS: dict[str, list[tuple]] = {
    "events":       [("created_at", "TEXT",    "''")],
    "command_log":  [("created_at", "TEXT",    "''"),
                     ("result",     "TEXT",    "''"),
                     ("blocked",    "INTEGER", "0"),
                     ("remote",     "INTEGER", "0")],
    "conversations":[("created_at", "TEXT",    "''"),
                     ("tools_used", "TEXT",    "''"),
                     ("ai_model",   "TEXT",    "'groq'")],
    "notes":        [("created_at", "TEXT",    "''"),
                     ("updated_at", "TEXT",    "''")],
    "config":       [("updated_at", "TEXT",    "''")],
    "memory_facts": [("created_at", "TEXT",    "''"),
                     ("last_used",  "TEXT",    "''")],
    "heartbeat_log":[("created_at", "TEXT",    "''")],
    "alarms":       [("created_at", "TEXT",    "''")],
}

# legacy column names that may hold timestamp data in old DBs
_LEGACY_TS_COLS = ("timestamp", "ts", "time", "created", "date")


def _sqlite_migrate(conn: sqlite3.Connection) -> None:
    """
    Idempotent schema migration: adds any missing columns to existing tables.
    Uses PRAGMA table_info — never drops or renames anything.
    Called from _sqlite_init() under db_lock, BEFORE returning to the caller.
    """
    for table, required in _REQUIRED_COLUMNS.items():
        # Skip if table doesn't exist yet (new install — _SCHEMA creates it)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        if cur.fetchone() is None:
            continue

        existing = {
            row["name"]: row
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

        for col_name, col_type, col_default in required:
            if col_name in existing:
                continue   # already present — idempotent

            # ADD COLUMN
            ddl = (
                f"ALTER TABLE {table} "
                f"ADD COLUMN {col_name} {col_type} "
                f"DEFAULT {col_default}"
            )
            conn.execute(ddl)
            log.warning(
                "[DB MIGRATE] ALTER TABLE %s ADD COLUMN %s %s DEFAULT %s",
                table, col_name, col_type, col_default
            )

            # Backfill created_at / updated_at from any legacy timestamp column
            if col_name in ("created_at", "updated_at"):
                for legacy in _LEGACY_TS_COLS:
                    if legacy in existing:
                        conn.execute(
                            f"UPDATE {table} SET {col_name} = {legacy} "
                            f"WHERE {col_name} IS NULL OR {col_name} = ''"
                        )
                        log.warning(
                            "[DB MIGRATE] Backfilled %s.%s from legacy column '%s'",
                            table, col_name, legacy
                        )
                        break
                else:
                    # No legacy column found — use current time
                    conn.execute(
                        f"UPDATE {table} SET {col_name} = datetime('now','localtime') "
                        f"WHERE {col_name} IS NULL OR {col_name} = ''"
                    )

    conn.commit()


def _sqlite_init() -> None:
    with db_lock:
        conn = _sqlite_connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            _sqlite_migrate(conn)   # add missing columns to existing DBs
            log.info("SQLite ready: %s", DB_PATH)
            print(f"[DB] ✅ SQLite ready: {DB_PATH}")
        finally:
            conn.close()


def _sqlite_adapt_legacy_insert(conn, sql: str, params: tuple = ()) -> tuple[str, tuple]:
    insert = re.fullmatch(
        r"\s*INSERT\s+(?:OR\s+(?:REPLACE|IGNORE)\s+)?INTO\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)\s*;?\s*",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not insert:
        return sql, params
    table = insert.group(1).lower()
    columns = [column.strip() for column in insert.group(2).split(",")]
    values = [value.strip() for value in insert.group(3).split(",")]
    provided = {column.strip('"`[]').lower(): index for index, column in enumerate(columns)}
    required = conn.execute(f"PRAGMA table_info({table})").fetchall()
    extra_params = []
    for column in required:
        name = column[1]
        normalized_name = name.lower()
        if (not column[3] or column[4] is not None or column[5]
                or normalized_name in provided):
            continue

        is_timestamp = any(
            marker in normalized_name
            for marker in ("timestamp", "created", "updated", "_at")
        )
        source_names = (
            (("updated_at", "created_at") if "updated" in normalized_name
             else ("created_at", "updated_at"))
            if is_timestamp
            else ()
        )
        source_index = next(
            (provided[source] for source in source_names if source in provided),
            None,
        )
        source_param_index = (
            sum(value == "?" for value in values[:source_index])
            if source_index is not None
            else None
        )
        if source_param_index is not None and source_param_index < len(params):
            fallback = params[source_param_index]
        elif is_timestamp:
            fallback = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif "INT" in str(column[2]).upper():
            fallback = 0
        elif any(marker in str(column[2]).upper() for marker in ("REAL", "FLOA", "DOUB", "NUM")):
            fallback = 0
        elif "BLOB" in str(column[2]).upper():
            fallback = b""
        else:
            fallback = ""

        columns.append(name)
        values.append("?")
        extra_params.append(fallback)
        provided[normalized_name] = len(params) + len(extra_params) - 1

    if extra_params:
        prefix = insert.group(0).split("(", 1)[0]
        sql = f"{prefix}({','.join(columns)}) VALUES({','.join(values)})"
        params = (*params, *extra_params)
    return sql, params


def _sqlite_write(sql: str, params: tuple = ()) -> bool:
    with db_lock:
        conn = _sqlite_connect()
        try:
            sql, params = _sqlite_adapt_legacy_insert(conn, sql, params)
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


def _sqlite_write_many(statements: list[tuple[str, tuple]]) -> bool:
    with db_lock:
        conn = _sqlite_connect()
        try:
            for sql, params in statements:
                sql, params = _sqlite_adapt_legacy_insert(conn, sql, params)
                conn.execute(sql, params)
            conn.commit()
            return True
        except Exception as exc:
            log.error("sqlite_write_many failed (%s)", type(exc).__name__)
            conn.rollback()
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
PG_CONNECT_RETRIES = 3
PG_RETRY_DELAYS = (0.25, 0.5)


class PostgresUnavailableError(ConnectionError):
    pass


def _pg_dsn() -> str:
    return _postgres_url("DATABASE_URL")


def _is_pg_connection_error(error: Exception) -> bool:
    try:
        import psycopg2
    except ImportError:
        return False
    return isinstance(error, (psycopg2.OperationalError, psycopg2.InterfaceError))


def _retry_pg_connection(operation):
    for attempt in range(PG_CONNECT_RETRIES):
        try:
            return operation()
        except Exception as exc:
            if not _is_pg_connection_error(exc):
                raise
            if attempt == PG_CONNECT_RETRIES - 1:
                raise PostgresUnavailableError("PostgreSQL connection unavailable") from None
            time.sleep(PG_RETRY_DELAYS[attempt])


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
    def check_connection():
        pool = _get_pg_pool()
        conn = pool.getconn()
        broken = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()
        except Exception as exc:
            if _is_pg_connection_error(exc):
                broken = True
            conn.rollback()
            raise
        finally:
            pool.putconn(conn, close=broken)

    try:
        _retry_pg_connection(check_connection)
        print("[DB] ✅ PostgreSQL ready")
        log.info("PostgreSQL ready")
    except Exception as exc:
        log.error("PostgreSQL init failed (%s)", type(exc).__name__)
        raise


def _probe_postgres() -> bool:
    connection = None
    try:
        import psycopg2
        connection = psycopg2.connect(_pg_dsn(), connect_timeout=5)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _postgres_recovery_worker() -> None:
    while True:
        time.sleep(PG_RECOVERY_INTERVAL_SECONDS)
        if _probe_postgres():
            log.error("Neon is reachable again; SQLite remains active; no data sync performed")
            return


def _start_postgres_recovery_monitor() -> None:
    threading.Thread(
        target=_postgres_recovery_worker,
        name="NeonRecoveryMonitor",
        daemon=True,
    ).start()


def _postgres_write(sql: str, params: tuple = ()) -> bool:
    pg_sql = _pg_placeholder(sql)

    def write_once():
        pool = _get_pg_pool()
        conn = None
        broken = False
        try:
            with db_lock:
                conn = pool.getconn()
                with conn.cursor() as cur:
                    cur.execute(pg_sql, params if params else None)
                conn.commit()
                return True
        except Exception as exc:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if _is_pg_connection_error(exc):
                broken = True
                raise
            log.error("pg_write failed (%s) | SQL: %s", type(exc).__name__, pg_sql[:120])
            return False
        finally:
            if conn:
                pool.putconn(conn, close=broken)

    return _retry_pg_connection(write_once)


def _postgres_write_many(statements: list[tuple[str, tuple]]) -> bool:
    def write_once():
        pool = _get_pg_pool()
        conn = None
        broken = False
        try:
            with db_lock:
                conn = pool.getconn()
                with conn.cursor() as cursor:
                    for sql, params in statements:
                        cursor.execute(_pg_placeholder(sql), params if params else None)
                conn.commit()
                return True
        except Exception as exc:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if _is_pg_connection_error(exc):
                broken = True
                raise
            log.error("pg_write_many failed (%s)", type(exc).__name__)
            return False
        finally:
            if conn:
                pool.putconn(conn, close=broken)

    return _retry_pg_connection(write_once)


def _postgres_read(sql: str, params: tuple = ()) -> list[dict]:
    pg_sql = _pg_placeholder(sql)

    def read_once():
        import psycopg2.extras
        pool = _get_pg_pool()
        conn = None
        broken = False
        try:
            conn = pool.getconn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(pg_sql, params if params else None)
                result = [dict(row) for row in cur.fetchall()]
            conn.commit()
            return result
        except Exception as exc:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if _is_pg_connection_error(exc):
                broken = True
                raise
            log.error("pg_read failed (%s) | SQL: %s", type(exc).__name__, pg_sql[:120])
            return []
        finally:
            if conn:
                pool.putconn(conn, close=broken)

    return _retry_pg_connection(read_once)


def _postgres_scalar(sql: str, params: tuple = ()):
    rows = _postgres_read(sql, params)
    return list(rows[0].values())[0] if rows else None


# ════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════
def init_db() -> None:
    global DB_BACKEND, SQLITE_FALLBACK_ACTIVE
    if DB_BACKEND == "sqlite":
        _sqlite_init()
    elif DB_BACKEND == "postgres":
        try:
            _postgres_init()
        except Exception as exc:
            SQLITE_FALLBACK_ACTIVE = True
            log.error("PostgreSQL unavailable (%s); falling back to SQLite", type(exc).__name__)
            print(f"[DB] ERROR: PostgreSQL unavailable ({type(exc).__name__}); falling back to SQLite")
            DB_BACKEND = "sqlite"
            _sqlite_init()
            _start_postgres_recovery_monitor()
    else:
        raise ValueError(f"[DB] Unknown DB_BACKEND='{DB_BACKEND}'. Use: sqlite | postgres")


def db_write(sql: str, params: tuple = ()) -> bool:
    if DB_BACKEND == "sqlite":    return _sqlite_write(sql, params)
    if DB_BACKEND == "postgres":  return _postgres_write(sql, params)
    raise NotImplementedError(f"db_write: unknown backend {DB_BACKEND}")


def db_write_many(statements: list[tuple[str, tuple]]) -> bool:
    if DB_BACKEND == "sqlite":    return _sqlite_write_many(statements)
    if DB_BACKEND == "postgres":  return _postgres_write_many(statements)
    raise NotImplementedError(f"db_write_many: unknown backend {DB_BACKEND}")


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
        # PostgreSQL config uses updated_at.
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

__all__ = [name for name in globals() if not name.startswith("_")]









