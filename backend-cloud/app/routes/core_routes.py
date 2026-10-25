"""
J.A.R.V.I.S v17.M — Core Routes
FIXED: M5 add_alert on do_command, L5 _pulse() imports cached at module level
"""
import time
import logging
from threading import Lock
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_from_directory

from app.config import (
    cache, stat_lock, _server_start,
    GROQ_KEY, GEMINI_KEY, OPENROUTER_KEY,
    ai_router_state, ai_router_lock,
    work_session, work_session_lock,
    discord_cfg, heartbeat_cfg, heartbeat_queue, heartbeat_lock
)
import app.db as database
from app.db import db_read, db_scalar, ts
from app.auth import sec_log_count
from app.command import cmd_route
from app.ai.agent import run_agent
from app.key_store import KeyStorageUnavailable, user_api_key_context

# ✅ FIX L5: import module-level objects once at module load, not inside _pulse() on every call
import app.monitor as _mon
import app.smarthome as _sh
import app.neural as _neu
from app.error_utils import api_errors

log  = logging.getLogger("jarvis.routes.core")
core = Blueprint("core", __name__)
_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_DB_HEALTH_CACHE_TTL = 30
_db_health_cache_lock = Lock()
_db_health_cache = {"checked_at": 0.0, "backend": None, "payload": None}


def _database_health_snapshot(now: float | None = None) -> dict:
    instant = time.monotonic() if now is None else now
    backend = database.DB_BACKEND
    with _db_health_cache_lock:
        cached = _db_health_cache
        if (cached["payload"] is not None and cached["backend"] == backend
                and instant - cached["checked_at"] < _DB_HEALTH_CACHE_TTL):
            return dict(cached["payload"])

        started = time.perf_counter()
        db_ok = db_scalar("SELECT 1") == 1
        latency_ms = round((time.perf_counter() - started) * 1000, 2) if backend == "postgres" else None
        vector_rows = None
        if backend == "postgres":
            try:
                counts = db_read("SELECT COUNT(*) AS count FROM memory_vectors")
                if counts:
                    vector_rows = int(counts[0].get("count", 0))
            except Exception:
                vector_rows = None
        payload = {
            "db_ok": db_ok,
            "db_backend": backend,
            "neon_select_1_latency_ms": latency_ms,
            "pgvector_row_count": vector_rows,
            "sqlite_fallback_active": bool(database.SQLITE_FALLBACK_ACTIVE),
        }
        _db_health_cache.update(checked_at=instant, backend=backend, payload=payload)
        return dict(payload)


def _pulse() -> dict:
    cam_active = any(c.get("active") for c in _mon.cameras.values())
    sh_on      = sum(1 for d in _sh.smarthome_devices.values() if d.get("state"))
    mon_cnt    = db_scalar("SELECT COUNT(*) FROM monitors WHERE active=1") or 0
    with heartbeat_lock:
        hb_len = len(heartbeat_queue)
    with _neu.neural_lock:
        nm_active = _neu.neural_state.get("active", False)
        nm_mode   = _neu.neural_state.get("mode", "normal")
    return {
        "camera_active":     cam_active,
        "cameras_count":     len(_mon.cameras),
        "smarthome_on":      sh_on,
        "smarthome_total":   len(_sh.smarthome_devices),
        "monitor_active":    mon_cnt,
        "heartbeat_pending": hb_len,
        "heartbeat_enabled": heartbeat_cfg.get("enabled", True),
        "ai_active":         ai_router_state.get("active", "groq"),
        "neural_active":     nm_active,
        "neural_mode":       nm_mode,
        "motion_enabled":    _mon.motion_cfg.get("enabled", False),
        "discord_enabled":   discord_cfg.get("enabled", False),
        "work_session_mins": int((time.time() - work_session["start"]) / 60),
    }


@core.route("/")
@api_errors
def serve_pc():
    return send_from_directory(_STATIC_DIR, "JARVIS.html")

@core.route("/mobile")
@api_errors
def serve_mobile():
    return send_from_directory(_STATIC_DIR, "mobile.html")


@core.route("/api/ping")
@api_errors
def ping():
    uptime = int(time.time() - _server_start)
    return jsonify({
        "status":     "online",
        "uptime":     uptime,
        "uptime_str": f"{uptime//3600}h {(uptime%3600)//60}m",
        "ts":         ts(),
        "ai":         ai_router_state.get("active", "groq"),
        "version":    "v17.M"
    })


@core.route("/api/stats")
@api_errors
def stats():
    with stat_lock:
        snap = dict(cache)
    uptime       = int(time.time() - _server_start)
    snap["uptime"]     = uptime
    snap["uptime_str"] = f"{uptime//3600}h {(uptime%3600)//60}m"
    snap["pulse"]      = _pulse()
    with ai_router_lock:
        snap["ai_router"] = {
            "active":     ai_router_state.get("active"),
            "groq_ok":    ai_router_state.get("groq_ok"),
            "gemini_ok":  ai_router_state.get("gemini_ok"),
            "or_ok":      ai_router_state.get("openrouter_ok"),
            "call_count": ai_router_state.get("call_count", 0),
            "fail_count": ai_router_state.get("fail_count", 0),
        }
    snap["keys"] = {
        "groq":       bool(GROQ_KEY),
        "gemini":     bool(GEMINI_KEY),
        "openrouter": bool(OPENROUTER_KEY),
    }
    return jsonify(snap)


@core.route("/api/pulse")
@api_errors
def pulse():
    return jsonify(_pulse())


@core.route("/api/command", methods=["POST","OPTIONS"])
@api_errors
def do_command():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    raw  = (data.get("command") or data.get("text") or "").strip()
    if not raw:
        return jsonify({"error": "No command provided"}), 400

    # ✅ FIX M2 + M5: thread-safe session update + add_alert
    with work_session_lock:
        work_session["commands_count"] += 1
        work_session["last_active"]     = time.time()

    # TASK-021 (Phase 2): cmd_route() only intercepts the 5 safety-critical
    # keyword-gated actions now (TASK-020) — safety_check() still runs on
    # every command first either way. Anything cmd_route doesn't recognize
    # falls straight through to run_agent below, so phrasing flexibility
    # (including Urdu/Roman-Urdu/casual English) isn't gated behind exact
    # string matching for anything except those 5 irreversible actions.
    cmd_result = cmd_route(raw)
    if cmd_result.get("handled"):
        sec_log_count(cmd=raw, blocked=cmd_result.get("blocked", False))
        return jsonify({"reply": cmd_result["result"], "source": "cmd_router"})

    session_id = data.get("session_id", "default")
    try:
        with user_api_key_context(g.current_user["username"]):
            from app.config import get_api_key

            if not any(get_api_key(name) for name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY")):
                return jsonify({"ok": False, "error": "no_api_key"}), 400
            result = run_agent(raw, session_id=session_id, ctx={
                "owner_username": g.current_user["username"],
            })
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503
    return jsonify({
        "reply":  result.get("reply", ""),
        "steps":  result.get("steps", []),
        "model":  result.get("model", ""),
        "source": "agent"
    })


@core.route("/api/sysinfo")
@api_errors
def sysinfo():
    import platform, psutil
    uptime = int(time.time() - _server_start)
    bat  = psutil.sensors_battery()
    vm   = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\" if platform.system()=="Windows" else "/")
    return jsonify({
        "os":         platform.system(),
        "os_ver":     platform.version()[:60],
        "hostname":   platform.node(),
        "cpu_cores":  psutil.cpu_count(logical=True),
        "cpu_pct":    cache.get("cpu", 0),
        "ram_total":  round(vm.total/1024**3, 1),
        "ram_used":   round(vm.used/1024**3,  1),
        "ram_pct":    vm.percent,
        "battery":    round(bat.percent) if bat else None,
        "charging":   bat.power_plugged  if bat else None,
        "disk_total": round(disk.total/1024**3, 1),
        "disk_used":  round(disk.used/1024**3,  1),
        "disk_pct":   disk.percent,
        "uptime":     uptime,
        "uptime_str": f"{uptime//3600}h {(uptime%3600)//60}m",
        "jarvis_ver": "v17.M",
    })


@core.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "v17.M"})


@core.route("/api/health/details")
@api_errors
def health_details():
    """Deep health-check endpoint (L7).
    TASK-014: now genuinely verifies DB connectivity, all 3 AI providers
    (not just Groq), and background-thread liveness — not just that the
    Flask process is up and responding."""
    import threading as _threading
    import psutil

    # ── Database ───────────────────────────────────────────────────
    db_health = _database_health_snapshot()
    db_ok = db_health["db_ok"]

    # ── CPU headroom (existing resource check, kept as-is) ──────────
    cpu_ok = psutil.cpu_percent(interval=0.1) < 95

    # ── AI providers: configured + last-known-reachable ──────────────
    # Not live-probed on every poll — that would burn API quota and add
    # latency to a health check. ai_router_state is kept current by every
    # real call in call_groq/call_gemini/call_openrouter (ai_engine.py),
    # so "last_ok" reflects the most recent real attempt, defaulting
    # optimistic (True) until a call actually proves otherwise.
    with ai_router_lock:
        providers = {
            "groq":       {"configured": bool(GROQ_KEY),       "last_ok": ai_router_state.get("groq_ok", False)},
            "gemini":     {"configured": bool(GEMINI_KEY),     "last_ok": ai_router_state.get("gemini_ok", False)},
            "openrouter": {"configured": bool(OPENROUTER_KEY), "last_ok": ai_router_state.get("openrouter_ok", False)},
        }
    ai_available = any(p["configured"] and p["last_ok"] for p in providers.values())

    # ── Background threads: actually alive, not assumed ──────────────
    # monitor.py / neural.py spawn these as fire-and-forget daemon threads
    # with distinctive names but no stored reference — threading.enumerate()
    # is the process-wide live-thread registry, so this checks reality
    # instead of just trusting start_background_threads() ran once at boot.
    expected_threads = ["WindowTracker", "SysMonitor", "MonitorEngine",
                        "SysEventMon", "HeartbeatEngine", "ReminderScheduler"]
    live_names = {t.name for t in _threading.enumerate() if t.is_alive()}
    threads    = {name: (name in live_names) for name in expected_threads}
    threads_ok = all(threads.values())

    core_ok = db_ok and threads_ok   # DB + threads = "is JARVIS actually functioning"
    if not core_ok:
        status, code = "unhealthy", 503
    elif not (ai_available and cpu_ok):
        status, code = "degraded", 200
    else:
        status, code = "healthy", 200

    return jsonify({
        "status":       status,
        "db":           "ok" if db_ok else "error",
        "db_backend":   db_health["db_backend"],
        "neon_select_1_latency_ms": db_health["neon_select_1_latency_ms"],
        "pgvector_row_count": db_health["pgvector_row_count"],
        "sqlite_fallback_active": db_health["sqlite_fallback_active"],
        "cpu_ok":       cpu_ok,
        "ai_providers": providers,
        "ai_available": ai_available,
        "threads":      threads,
        "threads_ok":   threads_ok,
        "uptime":       int(time.time() - _server_start),
        "version":      "v17.M",
    }), code
