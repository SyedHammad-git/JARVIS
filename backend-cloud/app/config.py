"""
J.A.R.V.I.S v17.M — Global Configuration & State
FIXED: H3 secret key, M1 GEMINI_URL, M2 work_session lock, M4 ai_router lock
"""
import os
import secrets
import logging
from contextvars import ContextVar
import time
from threading import Lock

from app.bind import resolve_bind_host
from app.db import cfg_get, cfg_set

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Execution mode (v18): local = this PC runs device tools; remote = Electron client
_EXEC_RAW = os.environ.get("EXECUTION_MODE", "local").lower().strip()
EXECUTION_MODE = _EXEC_RAW if _EXEC_RAW in ("local", "remote") else "local"
DEVICE_ID = os.environ.get("DEVICE_ID", "pc-primary").strip() or "pc-primary"
DEVICE_GATEWAY = os.environ.get("DEVICE_GATEWAY", "on").lower().strip() != "off"

# ── Optional dependencies ──────────────────────────────────────────
try:
    import requests as _req; REQUESTS_OK = True
except ImportError:
    _req = None; REQUESTS_OK = False
    print("[WARN] pip install requests")

try:
    import cv2; CV2_OK = True
except ImportError:
    cv2 = None; CV2_OK = False

try:
    from duckduckgo_search import DDGS; DDGS_OK = True
except ImportError:
    DDGS = None; DDGS_OK = False

try:
    import pyperclip; CLIP_OK = True
except ImportError:
    pyperclip = None; CLIP_OK = False

TUYA_OK = False
try:
    import tuyapy; TUYA_OK = True
except ImportError:
    pass

# ── Server start epoch ────────────────────────────────────────────
_server_start = time.time()

# ── AI keys & URLs ────────────────────────────────────────────────
GROQ_KEY       = os.environ.get("GROQ_KEY", "")
GEMINI_KEY     = os.environ.get("GEMINI_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
WEATHER_KEY    = os.environ.get("WEATHER_KEY", "")

_API_KEY_NAMES = {"GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY"}
_API_KEY_ENV_SNAPSHOT = {
    name: os.environ.get(name) for name in _API_KEY_NAMES
}
_user_api_keys: ContextVar[dict[str, str] | None] = ContextVar("user_api_keys", default=None)
_key_log = logging.getLogger("jarvis.config")
_server_fallback_warning_logged = False

def server_key_fallback_enabled() -> bool:
    return os.environ.get("SERVER_FALLBACK_KEYS", "").strip() == "1"


def multi_user_mode() -> bool:
    return (
        os.environ.get("JARVIS_ENV", "").strip().lower() == "production"
        or bool(os.environ.get("CLERK_ISSUER", "").strip())
    )


def _warn_server_fallback_enabled() -> None:
    global _server_fallback_warning_logged
    if server_key_fallback_enabled() and not _server_fallback_warning_logged:
        _key_log.warning(
            "SERVER_FALLBACK_KEYS=1: server-wide provider keys are enabled for all users and system tasks"
        )
        _server_fallback_warning_logged = True


_warn_server_fallback_enabled()


def get_api_key(name: str) -> str:
    if name not in _API_KEY_NAMES:
        raise ValueError(f"Unsupported API key name: {name}")
    _warn_server_fallback_enabled()
    fallback_enabled = server_key_fallback_enabled()
    user_keys = _user_api_keys.get()
    if user_keys is not None:
        user_key = user_keys.get(name, "")
        if user_key:
            return user_key
        if not fallback_enabled:
            return ""
    elif multi_user_mode() and not fallback_enabled:
        return ""
    value = os.environ.get(name)
    if value != _API_KEY_ENV_SNAPSHOT[name]:
        return value or ""
    return globals()[name]


def set_user_api_keys(keys: dict[str, str]):
    return _user_api_keys.set(dict(keys))


def reset_user_api_keys(token) -> None:
    _user_api_keys.reset(token)


def refresh_api_keys() -> None:
    global GROQ_KEY, GEMINI_KEY, OPENROUTER_KEY, WEATHER_KEY, _API_KEY_ENV_SNAPSHOT
    GROQ_KEY = os.environ.get("GROQ_KEY", "")
    GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
    OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
    WEATHER_KEY = os.environ.get("WEATHER_KEY", "")
    _API_KEY_ENV_SNAPSHOT = {
        name: os.environ.get(name) for name in _API_KEY_NAMES
    }


GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Build the Gemini URL dynamically so runtime key changes work and empty keys
# do not produce malformed ?key= URLs.
def get_gemini_url(pro: bool = False, key: str | None = None) -> str:
    if key is None:
        key = get_api_key("GEMINI_KEY")
    model = "gemini-4-argon" if pro else "gemini-3.8-flash"
    return (f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}")

OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-haiku-5.5"

# Keep these for backward compatibility — callers should prefer get_gemini_url().
GEMINI_URL     = get_gemini_url(pro=False)
GEMINI_PRO_URL = get_gemini_url(pro=True)

def _check_api_keys():
    missing = [name for name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY")
               if not get_api_key(name)]
    if missing:
        print(f"[CONFIG] [WARN] Missing provider keys: {', '.join(missing)}")
    else:
        print("[CONFIG] [INFO] All AI keys loaded")
    if get_api_key("WEATHER_KEY"):
        print("[CONFIG] [INFO] WEATHER_KEY active (OpenWeatherMap)")
    else:
        print("[CONFIG] [WARN] WEATHER_KEY missing; wttr.in fallback active")

_check_api_keys()

# ── PIN init ──────────────────────────────────────────────────────
_env_pin = os.environ.get("JARVIS_PIN", "").strip()
if _env_pin and _env_pin.isdigit():
    if not cfg_get("pin", ""):
        cfg_set("pin", _env_pin)
        print("[CONFIG] [INFO] PIN loaded from environment")
else:
    if not cfg_get("pin", ""):
        cfg_set("pin", "1234")
        print("[CONFIG] [WARN] Default PIN 1234 set; change via /api/pin/change")

# ── ✅ FIX H3: SECRET_KEY — never use a known fallback in production ─
# Generate a random key and store it in DB so it survives restarts
_stored_secret = cfg_get("flask_secret", "")
if not _stored_secret:
    _stored_secret = secrets.token_hex(32)
    cfg_set("flask_secret", _stored_secret)
    print("[CONFIG] [INFO] Flask SECRET_KEY generated and stored in DB")
FLASK_SECRET = os.environ.get("FLASK_SECRET", _stored_secret)

# ── Locks ─────────────────────────────────────────────────────────
ai_lock           = Lock()   # guards AI model call dispatch
agent_lock        = Lock()   # non-blocking guard on run_agent() — separate from ai_lock so the
                              # neural heartbeat (route_ai_call) can't be blocked by, or block, a
                              # user-initiated /api/agent or /api/command request
stat_lock         = Lock()   # guards cache dict
work_session_lock = Lock()   # ✅ FIX M2: guards work_session mutations
ai_router_lock    = Lock()   # ✅ FIX M4: guards ai_router_state counter mutations

# ── AI router state ───────────────────────────────────────────────
ai_router_state = {
    "active": "groq", "groq_ok": True, "gemini_ok": True, "openrouter_ok": True,
    "last_switch": "", "switch_reason": "", "call_count": 0, "fail_count": 0,
    # Circuit-breaker: after GROQ_FAIL_THRESHOLD consecutive failures, skip
    # even attempting Groq until groq_cooldown_until — avoids paying the
    # TASK-012 retry+backoff cost on every single call to a provider that's
    # currently known to be down, and falls through to OpenRouter/Gemini
    # immediately instead.
    "groq_fail_streak": 0, "groq_cooldown_until": 0.0,
}
GROQ_FAIL_THRESHOLD = 3
GROQ_COOLDOWN_SECS  = 30

# ── Stats cache (written by monitor thread every 2 s) ─────────────
cache = {
    "cpu": 0, "ram": 0, "ram_used": 0, "ram_total": 0,
    "battery": 0, "charging": False,
    "net_down": 0.0, "net_up": 0.0,
    "disk_pct": 0, "disk_used": 0, "disk_total": 0,
    "alerts": [], "processes": [],
    "sec_stats": {"commands": 0, "blocked": 0, "ok": 0, "remote": 0},
    "active_window": "", "active_app": ""
}

# ── Discord config ─────────────────────────────────────────────────
_env_webhook = os.environ.get("DISCORD_WEBHOOK", "").strip()
_db_webhook  = cfg_get("discord_webhook_url", "")
if _env_webhook and not _db_webhook:
    cfg_set("discord_webhook_url", _env_webhook)
    cfg_set("discord_enabled", "true")
    print("[CONFIG] [INFO] DISCORD_WEBHOOK loaded from environment")

discord_cfg = {
    "webhook_url": _db_webhook or _env_webhook,
    "enabled": cfg_get("discord_enabled", "false") == "true"
}

# ── Security ──────────────────────────────────────────────────────
BLACKLIST = [
    "del ", "del/", "/del", "rmdir", "format", "erase", "reg delete",
    "diskpart", "rd /s", "del /f", "cipher /w", "bcdedit", "bootrec", "format c:",
    "taskkill /f", ":(){:|:&}", "sudo rm", "rm -rf", "wget http", "curl http",
]
security_settings = {
    "blacklist": True, "audit": True, "remote": True, "guardrail": True, "autolock": False
}

# ── Work session ──────────────────────────────────────────────────
# ✅ FIX M2: All mutations MUST acquire work_session_lock
work_session = {
    "start": time.time(), "last_active": time.time(),
    "commands_count": 0, "break_reminded": False,
    "last_break_remind": 0, "last_hydration": 0,
    "last_sleep_warn": 0, "last_proactive": 0,
    "coding_minutes": 0
}

# ── Heartbeat engine state ────────────────────────────────────────
heartbeat_cfg = {
    "enabled": True, "interval": 30,
    "cpu_threshold": 85, "ram_threshold": 88,
    "battery_low": 15, "coding_break_mins": 90,
    "silence_until": 0, "last_run": 0
}
heartbeat_queue = []
heartbeat_lock  = Lock()
