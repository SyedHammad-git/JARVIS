"""J.A.R.V.I.S v17.M — AI Routes Blueprint"""
import hashlib
import logging
import secrets
import time
from flask import Blueprint, g, jsonify, request
from app.config import (
    ai_router_state, ai_router_lock,
    work_session, work_session_lock,
)
from app.db import db_read, db_write, db_write_returning
from app.devices.gateway import first_online_device
from app.ai.agent import run_agent, tool_confirmation_signature
from app.ai.engine import call_gemini, route_ai_call, build_jarvis_context, AGENT_SYS_BASE
from app.key_store import KeyStorageUnavailable, user_api_key_context
from app.neural import (
    get_heartbeat_queue,
    neural_lock,
    owner_neural_state,
    push_system_event,
    update_heartbeat_config,
)
from app.notifications import send_os_notification
from app.error_utils import api_errors

log = logging.getLogger("jarvis.routes.ai")
ai  = Blueprint("ai", __name__)


@ai.route("/api/agent", methods=["POST","OPTIONS"])
@api_errors
def agent_chat():
    if request.method == "OPTIONS": return "", 204
    try:
        with user_api_key_context(g.current_user["username"]):
            return _agent_chat_with_user_key_context()
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503


def _agent_chat_with_user_key_context():
    from app.config import get_api_key
    if not any(get_api_key(name) for name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY")):
        return jsonify({"ok": False, "error": "no_api_key"}), 400
    data       = request.get_json(silent=True) or {}
    user_input = (data.get("message") or data.get("text") or data.get("input") or "").strip()
    if not user_input:
        return jsonify({"error": "No message provided"}), 400
    session_id = data.get("session_id", "default")
    session_id = str(session_id)[:120]
    confirmed  = bool(data.get("confirmed"))
    confirmation_nonce = None
    confirmed_signature = None
    if confirmed:
        supplied_nonce = str(data.get("confirmation_nonce") or "")
        nonce_hash = hashlib.sha256(supplied_nonce.encode("utf-8")).hexdigest()
        pending = db_write_returning(
            "DELETE FROM pending_confirmations WHERE owner_username=? AND session_id=? "
            "AND nonce_hash=? AND message=? AND expires_at>? RETURNING tool_signature",
            (g.current_user["username"], session_id, nonce_hash, user_input, time.time()),
        )
        if not pending:
            return jsonify({"ok": False, "error": "confirmation_expired_or_invalid"}), 403
        confirmation_nonce = supplied_nonce
        confirmed_signature = pending[0]["tool_signature"]

    owner = g.current_user["username"]
    requested_device_id = str(data.get("device_id") or "").strip()
    device_id = requested_device_id or first_online_device(owner)
    result = run_agent(
        user_input,
        session_id=session_id,
        ctx={
            "confirmed": confirmed,
            "confirmed_signature": confirmed_signature,
            "confirmation_nonce": confirmation_nonce,
            "owner_username": owner,
            "device_id": device_id,
            "snapshot_user": owner,
        },
    )
    confirmation_response = {}
    if result.get("needs_confirmation"):
        nonce = secrets.token_urlsafe(24)
        expires_at = time.time() + 60
        stored = db_write(
            "INSERT INTO pending_confirmations(owner_username,session_id,nonce_hash,message,tool_signature,expires_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(owner_username,session_id) DO UPDATE SET "
            "nonce_hash=excluded.nonce_hash,message=excluded.message,"
            "tool_signature=excluded.tool_signature,expires_at=excluded.expires_at",
            (
                owner,
                session_id,
                hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
                user_input,
                tool_confirmation_signature(result.get("tool", ""), result.get("args") or {}),
                expires_at,
            ),
        )
        if not stored:
            return jsonify({"ok": False, "error": "confirmation_unavailable"}), 503
        confirmation_response = {
            "needs_confirmation": True,
            "confirmation_nonce": nonce,
            "confirmation_expires_in": 60,
            "tool": result.get("tool"),
            "args": result.get("args"),
            "reason": result.get("reason"),
        }
    return jsonify({
        "ok":         result.get("ok"),
        "reply":      result.get("reply",""),
        "steps":      result.get("steps",[]),
        "iterations": result.get("iterations",0),
        "model":      result.get("model",""),
        **confirmation_response,
    })


@ai.route("/api/agent/clear", methods=["POST","OPTIONS"])
@api_errors
def agent_clear():
    if request.method == "OPTIONS": return "", 204
    session_id = str((request.get_json(silent=True) or {}).get("session_id", "default"))[:120]
    db_write(
        "DELETE FROM conversations WHERE owner_username=? AND session_id=?",
        (g.current_user["username"], session_id),
    )
    return jsonify({"ok": True, "message": "Conversation cleared, Sir."})


@ai.route("/api/neural", methods=["POST","OPTIONS"])
@api_errors
def neural_endpoint():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    with work_session_lock:
        work_session["last_active"]     = time.time()
        work_session["commands_count"] += 1

    try:
        with user_api_key_context(g.current_user["username"]):
            from app.config import get_api_key

            if not any(get_api_key(name) for name in ("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY")):
                return jsonify({"ok": False, "error": "no_api_key"}), 400
            ctx = build_jarvis_context(g.current_user["username"])
            messages = [
                {"role": "system", "content": AGENT_SYS_BASE + "\n" + ctx},
                {"role": "user", "content": text},
            ]
            reply, model, _ = route_ai_call(messages, task_type="chat")
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503
    with neural_lock:
        state = owner_neural_state(g.current_user["username"])
        state["last_cmd"] = text
        state["last_reply"] = reply
        state["conv_state"] = "idle"
    return jsonify({"ok": True, "reply": reply, "model": model})


@ai.route("/api/ai/router", methods=["GET"])
@api_errors
def ai_router_status():
    with ai_router_lock:
        snap = dict(ai_router_state)
    return jsonify(snap)


@ai.route("/api/ai/gemini", methods=["POST","OPTIONS"])
@api_errors
def ai_gemini():
    if request.method == "OPTIONS": return "", 204
    data    = request.get_json(silent=True) or {}
    prompt  = (data.get("prompt") or data.get("text") or "").strip()
    img_b64 = data.get("image_base64")
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400
    try:
        with user_api_key_context(g.current_user["username"]):
            from app.config import get_api_key

            if not get_api_key("GEMINI_KEY"):
                return jsonify({"ok": False, "error": "no_api_key"}), 400
            result = call_gemini(prompt, image_base64=img_b64)
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503
    return jsonify(result)


@ai.route("/api/neural/activate", methods=["POST","OPTIONS"])
@api_errors
def neural_activate():
    if request.method == "OPTIONS": return "", 204
    with neural_lock:
        state = owner_neural_state(g.current_user["username"])
        state["active"] = True
        state["conv_state"] = "idle"
    push_system_event("neural", "Neural Mode activated, Sir.",
                      owner_username=g.current_user["username"])
    return jsonify({"ok": True, "active": True})


@ai.route("/api/neural/deactivate", methods=["POST","OPTIONS"])
@api_errors
def neural_deactivate():
    if request.method == "OPTIONS": return "", 204
    with neural_lock:
        state = owner_neural_state(g.current_user["username"])
        state["active"] = False
        state["conv_state"] = "idle"
    return jsonify({"ok": True, "active": False})


@ai.route("/api/neural/status", methods=["GET"])
@api_errors
def neural_status():
    with neural_lock:
        snap = dict(owner_neural_state(g.current_user["username"]))
    return jsonify(snap)


@ai.route("/api/neural/silence", methods=["POST","OPTIONS"])
@api_errors
def neural_silence():
    if request.method == "OPTIONS": return "", 204
    minutes = (request.get_json(silent=True) or {}).get("minutes", 30)
    update_heartbeat_config(
        g.current_user["username"], {"silence_until": time.time() + minutes * 60}
    )
    return jsonify({"ok": True, "silenced_for_minutes": minutes})


@ai.route("/api/neural/conv_state", methods=["POST","OPTIONS"])
@api_errors
def neural_conv_state():
    if request.method == "OPTIONS": return "", 204
    state = (request.get_json(silent=True) or {}).get("state","idle")
    with neural_lock:
        owner_neural_state(g.current_user["username"])["conv_state"] = state
    return jsonify({"ok": True, "conv_state": state})


@ai.route("/api/speak", methods=["POST","OPTIONS"])
@api_errors
def speak():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    msg  = (data.get("message") or data.get("text") or "").strip()
    if not msg:
        return jsonify({"error": "No message"}), 400
    send_os_notification(
        "J.A.R.V.I.S",
        msg,
        owner_username=g.current_user["username"],
    )
    return jsonify({"ok": True})


@ai.route("/api/events/poll", methods=["GET"])
@api_errors
def events_poll():
    with neural_lock:
        owner = g.current_user["username"]
        events = [
            event for event in neural_state.get("event_queue", [])
            if event.get("owner_username") == owner
        ]
        neural_state["event_queue"] = [
            event for event in neural_state.get("event_queue", [])
            if event.get("owner_username") != owner
        ]
    hb = get_heartbeat_queue(g.current_user["username"], clear=True)
    return jsonify({"events": events, "heartbeat": hb, "count": len(events)+len(hb)})


@ai.route("/api/system/events", methods=["GET"])
@api_errors
def system_events():
    rows = db_read(
        "SELECT * FROM events WHERE owner_username=? ORDER BY id DESC LIMIT 50",
        (g.current_user["username"],),
    )
    return jsonify({"events": rows, "count": len(rows)})
