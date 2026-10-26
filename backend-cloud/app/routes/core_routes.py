"""
J.A.R.V.I.S v18.0.0 — Core Routes
FIXED: M5 add_alert on do_command, L5 _pulse() imports cached at module level
"""
import time
import logging
from threading import Lock
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, redirect, request, send_from_directory

from app.config import (
    cache, stat_lock, _server_start,
    GROQ_KEY, GEMINI_KEY, OPENROUTER_KEY,
    ai_router_state, ai_router_lock,
    work_session, work_session_lock,
    discord_cfg
)
import app.db as database
from app.db import db_read, db_scalar, ts
from app.ai.agent import run_agent
from app.key_store import KeyStorageUnavailable, user_api_key_context
from app.devices.gateway import first_online_device

# ✅ FIX L5: import module-level objects once at module load, not inside _pulse() on every call
import app.smarthome as _sh
import app.neural as _neu
from app.error_utils import api_errors

log  = logging.getLogger("jarvis.routes.core")
core = Blueprint("core", __name__)
_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_DB_HEALTH_CACHE_TTL = 30
_db_health_cache_lock = Lock()
_db_health_cache = {"checked_at": 0.0, "backend": None, "owner": None, "payload": None}


def _database_health_snapshot(owner_username: str = "", now: float | None = None) -> dict:
    instant = time.monotonic() if now is None else now
    backend = database.DB_BACKEND
    with _db_health_cache_lock:
        cached = _db_health_cache
        if (cached["payload"] is not None and cached["backend"] == backend
                and cached["owner"] == owner_username
                and instant - cached["checked_at"] < _DB_HEALTH_CACHE_TTL):
            return dict(cached["payload"])

        started = time.perf_counter()
        db_ok = db_scalar("SELECT 1") == 1
        latency_ms = round((time.perf_counter() - started) * 1000, 2) if backend == "postgres" else None
        vector_rows = None
        if backend == "postgres":
            try:
                counts = db_read(
                    "SELECT COUNT(*) AS count FROM memory_vectors WHERE owner_username=?",
                    (owner_username,),
                )
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
        _db_health_cache.update(
            checked_at=instant, backend=backend, owner=owner_username, payload=payload
        )
        return dict(payload)


def _pulse(owner_username: str = "") -> dict:
    sh_on      = sum(1 for d in _sh.smarthome_devices.values() if d.get("state"))
    mon_cnt    = db_scalar(
        "SELECT COUNT(*) FROM monitors WHERE owner_username=? AND active=1",
        (owner_username,),
    ) or 0
    heartbeat_config = _neu.get_heartbeat_config(owner_username)
    hb_len = len(_neu.get_heartbeat_queue(owner_username))
    with _neu.neural_lock:
        owner_state = _neu.owner_neural_state(owner_username)
        nm_active = owner_state.get("active", False)
        nm_mode   = owner_state.get("mode", "normal")
    return {
        "smarthome_on":      sh_on,
        "smarthome_total":   len(_sh.smarthome_devices),
        "monitor_active":    mon_cnt,
        "heartbeat_pending": hb_len,
        "heartbeat_enabled": heartbeat_config.get("enabled", True),
        "ai_active":         ai_router_state.get("active", "groq"),
        "neural_active":     nm_active,
        "neural_mode":       nm_mode,
        "discord_enabled":   discord_cfg.get("enabled", False),
        "work_session_mins": int((time.time() - work_session["start"]) / 60),
    }


@core.route("/")
@api_errors
def serve_pc():
    if current_app.config.get("JARVIS_ENV") == "production":
        return redirect(current_app.config["LANDING_URL"], code=302)
    return send_from_directory(_STATIC_DIR, "JARVIS.html")

@core.route("/mobile")
@api_errors
def serve_mobile():
    if current_app.config.get("JARVIS_ENV") == "production":
        return redirect(current_app.config["LANDING_URL"], code=302)
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
        "version":    "v18.0.0"
    })


@core.route("/api/stats")
@api_errors
def stats():
    with stat_lock:
        snap = dict(cache)
        owner = g.current_user["username"]
        snap["alerts"] = [
            alert for alert in snap.get("alerts", [])
            if alert.get("owner_username") == owner
        ]
    uptime       = int(time.time() - _server_start)
    snap["uptime"]     = uptime
    snap["uptime_str"] = f"{uptime//3600}h {(uptime%3600)//60}m"
    snap["pulse"]      = _pulse(g.current_user["username"])
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
    return jsonify(_pulse(g.current_user["username"]))


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

    session_id = data.get("session_id", "default")
    try:
        with user_api_key_context(g.current_user["username"]):
            from app.config import get_api_key

            if not any(get_api_key(name) for name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY")):
                return jsonify({"ok": False, "error": "no_api_key"}), 400
            result = run_agent(raw, session_id=session_id, ctx={
                "owner_username": g.current_user["username"],
                "device_id": (
                    str(data.get("device_id") or "").strip()
                    or first_online_device(g.current_user["username"])
                ),
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
    uptime = int(time.time() - _server_start)
    return jsonify({
        "uptime":     uptime,
        "uptime_str": f"{uptime//3600}h {(uptime%3600)//60}m",
        "jarvis_ver": "v18.0.0",
    })


@core.route("/api/health")
@api_errors
def health():
    return jsonify(_health_payload())


def _online_device_count(owner_username: str | None = "") -> int:
    from app.devices.gateway import is_online
    if owner_username is None:
        from app.devices.gateway import online_device_ids
        return len(online_device_ids())
    devices = db_read(
        "SELECT device_id FROM devices WHERE owner_username=? AND revoked=0",
        (owner_username,),
    )
    return sum(1 for device in devices if is_online(device.get("device_id")))


def _health_payload() -> dict:
    owner = getattr(g, "current_user", {}).get("username")
    if owner is None:
        owner = ""
    health = _database_health_snapshot(owner)
    return {
        "status": "ok" if health["db_ok"] else "degraded",
        "version": "v18.0.0",
        "db_ok": health["db_ok"],
        "db_backend": health["db_backend"],
        "neon_select_1_latency_ms": health["neon_select_1_latency_ms"],
        "pgvector_row_count": health["pgvector_row_count"],
        "sqlite_fallback_active": health["sqlite_fallback_active"],
        "online_device_count": _online_device_count(
            getattr(g, "current_user", {}).get("username")
        ),
    }


@core.route("/api/health/details")
@api_errors
def health_details():
    """Return backend, database, vector, fallback, and device health only."""
    payload = _health_payload()
    with ai_router_lock:
        providers = {
            "groq": {"configured": bool(GROQ_KEY), "last_ok": ai_router_state.get("groq_ok", False)},
            "gemini": {"configured": bool(GEMINI_KEY), "last_ok": ai_router_state.get("gemini_ok", False)},
            "openrouter": {
                "configured": bool(OPENROUTER_KEY),
                "last_ok": ai_router_state.get("openrouter_ok", False),
            },
        }
    payload["ai_providers"] = providers
    payload["uptime"] = int(time.time() - _server_start)
    return jsonify(payload)
