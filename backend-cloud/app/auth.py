"""
J.A.R.V.I.S v17.M — Auth & Security Helpers
FIXED: H1 timing attack on verify_pin, H2 shell injection in safety_check
"""
import datetime
import logging
import subprocess
import threading

from config import BLACKLIST, security_settings, stat_lock, cache
from database import db_write, cfg_get, ts

log = logging.getLogger("jarvis.auth")

# ── TASK-001 fix: _BCRYPT_OK / _CHAIN_OPS were referenced but never defined,
# and secrets.compare_digest() was called without importing secrets. This
# crashed verify_pin() (PIN login/change) and safety_check() (every typed
# command + the agent's open_app tool) with a bare NameError. ──────────────
import secrets

try:
    import bcrypt
except ImportError:  # pragma: no cover
    raise RuntimeError(
        "[AUTH] bcrypt is required but not installed.\n"
        "  Run: pip install bcrypt>=4.0.0\n"
        "  Then restart JARVIS."
    )

# Shell chain/injection operators — used by safety_check()
_CHAIN_OPS = ["&&", "||", ";", "|", "`", "$(", ">", "<", "\n"]

# ── PIN verification ──────────────────────────────────────────────
def hash_pin(pin: str) -> str:
    """Hash PIN with bcrypt (required — no plaintext fallback)."""
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(provided_pin: str) -> bool:
    """Constant-time PIN verification with bcrypt."""
    stored = cfg_get("pin", "")
    if not stored:
        return False
    # Try bcrypt first if stored hash looks like bcrypt
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(provided_pin.encode(), stored.encode())
        except Exception:
            return False
    # Legacy plaintext compare — constant-time to prevent timing attacks.
    # Once verified, the caller should re-hash with bcrypt and store it.
    return secrets.compare_digest(str(provided_pin), str(stored))
def safety_check(cmd: str) -> tuple:
    """Return (safe: bool, matched_pattern: str)."""
    if not security_settings.get("blacklist", True):
        return True, ""
    c = cmd.lower().strip()
    # Blacklisted keywords
    for w in BLACKLIST:
        if w in c:
            return False, w
    # ✅ FIX H2: Shell chaining operators that bypass whitelist
    for op in _CHAIN_OPS:
        if op in cmd:
            return False, f"chain-op:{op}"
    return True, ""

# ── Shell execution ───────────────────────────────────────────────
def shell_exec(cmd: str) -> bool:
    """Fire-and-forget shell command. Safety check MUST be done by caller."""
    try:
        subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.debug("shell_exec: %s", cmd[:80])
        return True
    except Exception as e:
        log.error("shell_exec failed: %s | cmd: %s", e, cmd[:80])
        return False

# ── Alert helpers ─────────────────────────────────────────────────
def add_alert(msg: str):
    """Append alert to in-memory cache (bounded) and persist to DB async."""
    with stat_lock:
        ts_str = datetime.datetime.now().strftime("%H:%M:%S")
        cache["alerts"].append({"msg": msg, "ts": ts_str})
        if len(cache["alerts"]) > 50:
            cache["alerts"] = cache["alerts"][-50:]
    threading.Thread(
        target=db_write,
        args=("INSERT INTO events(type,message,created_at) VALUES(?,?,?)",
              ("alert", msg[:300], ts())),
        daemon=True
    ).start()

def sec_log_count(blocked=False, remote=False, cmd=""):
    """Increment security counters and write audit log entry."""
    with stat_lock:
        cache["sec_stats"]["commands"] += 1
        if blocked: cache["sec_stats"]["blocked"] += 1
        else:       cache["sec_stats"]["ok"]      += 1
        if remote:  cache["sec_stats"]["remote"]  += 1
    if security_settings.get("audit"):
        threading.Thread(
            target=db_write,
            args=("INSERT INTO command_log(command,blocked,remote,created_at) VALUES(?,?,?,?)",
                  (cmd[:200], 1 if blocked else 0, 1 if remote else 0, ts())),
            daemon=True
        ).start()
