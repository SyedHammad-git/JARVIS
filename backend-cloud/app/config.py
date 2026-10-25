"""
J.A.R.V.I.S v17.M — Global Configuration & State
FIXED: H3 secret key, M1 GEMINI_URL, M2 work_session lock, M4 ai_router lock
"""
import os
import secrets
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

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ✅ FIX M1: Build Gemini URL dynamically using a function so runtime key changes work
# and empty keys don't produce malformed ?key= URLs
def get_gemini_url(pro: bool = False) -> str:
    key = os.environ.get("GEMINI_KEY", GEMINI_KEY)
    model = "gemini-1.5-pro" if pro else "gemini-2.0-flash"
    return (f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}")

OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-3.5-haiku"

# Keep these for backward compat — but callers should prefer get_gemini_url()
GEMINI_URL     = get_gemini_url(pro=False)
GEMINI_PRO_URL = get_gemini_url(pro=True)

def _check_api_keys():
    missing = [k for k, v in [("GROQ_KEY", GROQ_KEY),
                                ("GEMINI_KEY", GEMINI_KEY),
                                ("OPENROUTER_KEY", OPENROUTER_KEY)] if not v]
    if missing:
        print(f"[CONFIG] ⚠  Missing .env keys: {', '.join(missing)}")
    else:
        print("[CONFIG] ✅ All AI keys loaded")
    if WEATHER_KEY:
        print("[CONFIG] ✅ WEATHER_KEY active (OpenWeatherMap)")
    else:
        print("[CONFIG] ⚠  WEATHER_KEY missing — wttr.in fallback active")

_check_api_keys()

# ── PIN init ──────────────────────────────────────────────────────
_env_pin = os.environ.get("JARVIS_PIN", "").strip()
if _env_pin and _env_pin.isdigit():
    if not cfg_get("pin", ""):
        cfg_set("pin", _env_pin)
        print("[CONFIG] ✅ PIN loaded from .env")
else:
    if not cfg_get("pin", ""):
        cfg_set("pin", "1234")
        print("[CONFIG] ⚠  Default PIN 1234 set — change via /api/pin/change")

# ── ✅ FIX H3: SECRET_KEY — never use a known fallback in production ─
# Generate a random key and store it in DB so it survives restarts
_stored_secret = cfg_get("flask_secret", "")
if not _stored_secret:
    _stored_secret = secrets.token_hex(32)
    cfg_set("flask_secret", _stored_secret)
    print("[CONFIG] ✅ Flask SECRET_KEY generated and stored in DB")
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
    print("[CONFIG] ✅ DISCORD_WEBHOOK loaded from .env")

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
