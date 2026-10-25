"""
╔══════════════════════════════════════════════════════════════════╗
║   J.A.R.V.I.S  v17.M  —  Application Entry Point               ║
║   FIXED: H3 random secret, M7 global error handlers, L7 health  ║
╚══════════════════════════════════════════════════════════════════╝
"""
import logging
import os
from pathlib import Path

# ── 2. Logging setup ──────────────────────────────────────────────
# TASK-031: every module already logs to its own named logger
# (jarvis.db, jarvis.auth, jarvis.ai, jarvis.agent, jarvis.command,
# jarvis.tools, jarvis.neural, jarvis.errors, ...) but there was no file
# behind any of it — only whatever the console happened to show at the
# time. A RotatingFileHandler on the root logger means a "random" failure
# can be traced after the fact from ~/JARVIS_Data/jarvis.log instead of
# needing to reproduce it live with the console open.
# (Path is computed here rather than imported from database.py, so this
# runs before database.py — and its own startup logging — is imported.)
from logging.handlers import RotatingFileHandler

_log_dir = Path(os.environ.get("JARVIS_DATA_DIR", Path(os.path.expanduser("~")) / "JARVIS_Data")).expanduser()
_log_dir.mkdir(parents=True, exist_ok=True)
_file_handler = RotatingFileHandler(
    _log_dir / "jarvis.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL","INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), _file_handler],
)
log = logging.getLogger("jarvis")

from flask import jsonify

from app import create_app, load_environment
from app.extensions import socketio

load_environment()

app = create_app()

try:
    from flask_limiter import Limiter
    _LIMITER_OK = True
except ImportError:
    _LIMITER_OK = False
    print("[SERVER] ⚠ flask-limiter not installed — pip install flask-limiter")

if _LIMITER_OK:
    from app.security import get_client_ip

    limiter = Limiter(
        get_client_ip,
        app=app,
        default_limits=["200 per minute"],
        storage_uri="memory://",
    )
    print("[SERVER] ✅ Rate limiter active (200 req/min default)")


# Import config AFTER dotenv so env vars are available
import app.config as app_config
app.config["SECRET_KEY"] = getattr(app_config, "FLASK_SECRET", app.config.get("SECRET_KEY"))
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

log.info("All blueprints registered — %d routes total",
         len(list(app.url_map.iter_rules())))

# ── 7. Global error handlers ─────────────────────────────────────
# ✅ FIX M7: catch unhandled 404 and 500 — never leak stack traces
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found", "code": 404}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed", "code": 405}), 405

@app.errorhandler(500)
def internal_error(e):
    log.error("Unhandled 500: %s", e)
    return jsonify({"error": "Internal server error", "code": 500}), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    # Pass werkzeug HTTPException through unchanged so 401/403/429 keep
    # their proper status codes instead of being wrapped as 500.
    from werkzeug.exceptions import HTTPException as _HTTPExc
    if isinstance(e, _HTTPExc):
        return e
    log.exception("Unhandled exception: %s", e)
    return jsonify({"error": "An unexpected error occurred", "code": 500}), 500

# ── 9. Startup banner ─────────────────────────────────────────────
from app.tools.registry import REGISTRY
from app.config import (
    GROQ_KEY, GEMINI_KEY, OPENROUTER_KEY, WEATHER_KEY,
    DDGS_OK, heartbeat_cfg,
)
from app.db import DB_PATH

print()
print("╔══════════════════════════════════════════════════════════╗")
print("║   J.A.R.V.I.S  v17.M  —  Enterprise Edition             ║")
print("║   Just A Rather Very Intelligent System                  ║")
print("║   Built by Hammad  •  github.com/SyedHammad-git         ║")
print("╠══════════════════════════════════════════════════════════╣")
print(f"║   Database    : {str(DB_PATH)[:46]}")
print(f"║   Groq        : {'✅ active' if GROQ_KEY else '❌ missing GROQ_KEY'}")
print(f"║   Gemini      : {'✅ active' if GEMINI_KEY else '❌ missing GEMINI_KEY'}")
print(f"║   OpenRouter  : {'✅ active' if OPENROUTER_KEY else '❌ missing OPENROUTER_KEY'}")
print(f"║   Weather     : {'✅ OWM active' if WEATHER_KEY else '⚠  wttr.in fallback'}")
print(f"║   DDG Search  : {'✅ web search ready' if DDGS_OK else '⚠  pip install duckduckgo-search'}")
print(f"║   Tools       : {len(REGISTRY)} agent tools")
print(f"║   Auth mode   : {os.environ.get('AUTH_MODE', 'local').lower()}")
print("║   Gateway     : Socket.IO /device")
print(f"║   Heartbeat   : {'✅ enabled' if heartbeat_cfg['enabled'] else '⏸  disabled'}")
print("╠══════════════════════════════════════════════════════════╣")
print("║   http://localhost:5000           Desktop UI             ║")
print("║   http://localhost:5000/mobile    Mobile UI              ║")
print("║   http://localhost:5000/api/ping  Health check           ║")
print("║   http://localhost:5000/api/health  Deep health check    ║")
print("╚══════════════════════════════════════════════════════════╝")
print()

# ── 10. Run ───────────────────────────────────────────────────────
# Flask-SocketIO WebSockets work with the Werkzeug development server and
# with Gunicorn gthread (Linux).
#
# Production (Linux, one process — multiple workers need sticky sessions
# plus a message queue such as Redis):
#   gunicorn --worker-class gthread --threads 100 -w 1 server:app
if __name__ == "__main__":
    if os.environ.get("JARVIS_ENV", "development").lower() == "production":
        raise RuntimeError("Production mode must be launched with Gunicorn; do not run wsgi.py directly")
    host  = app.config["JARVIS_HOST"]
    port  = int(os.environ.get("JARVIS_PORT", 5000))
    debug = os.environ.get("JARVIS_DEBUG", "false").lower() == "true"

    if debug:
        log.warning("DEBUG mode is ON — disable in production (JARVIS_DEBUG=false)")
    log.info("Starting Flask-SocketIO on %s:%d (Werkzeug, threading)", host, port)
    print(f"[JARVIS] Socket.IO gateway on http://{host}:{port}")
    socketio.run(
        app,
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
