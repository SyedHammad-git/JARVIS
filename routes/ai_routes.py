"""J.A.R.V.I.S v17.M — AI Routes Blueprint"""
import logging, time
from flask import Blueprint, jsonify, request
from config import (
    ai_router_state, ai_router_lock,
    work_session, work_session_lock,
    heartbeat_cfg, heartbeat_queue, heartbeat_lock
)
from database import db_read, db_write
from agent import run_agent
from ai_engine import call_gemini, route_ai_call, build_jarvis_context, AGENT_SYS_BASE
from neural import neural_state, neural_lock, push_system_event
from notifications import send_os_notification
from error_utils import api_errors

log = logging.getLogger("jarvis.routes.ai")
ai  = Blueprint("ai", __name__)


@ai.route("/api/agent", methods=["POST","OPTIONS"])
@api_errors
def agent_chat():
    if request.method == "OPTIONS": return "", 204
    data       = request.get_json(silent=True) or {}
    user_input = (data.get("message") or data.get("text") or data.get("input") or "").strip()
    if not user_input:
        return jsonify({"error": "No message provided"}), 400
    session_id = data.get("session_id", "default")
    result     = run_agent(user_input, session_id=session_id)
    return jsonify({
        "ok":         result.get("ok"),
        "reply":      result.get("reply",""),
        "steps":      result.get("steps",[]),
        "iterations": result.get("iterations",0),
        "model":      result.get("model",""),
    })


@ai.route("/api/agent/clear", methods=["POST","OPTIONS"])
@api_errors
def agent_clear():
    if request.method == "OPTIONS": return "", 204
    session_id = (request.get_json(silent=True) or {}).get("session_id","default")
    db_write("DELETE FROM conversations WHERE session_id=?", (session_id,))
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

    ctx      = build_jarvis_context()
    messages = [
        {"role":"system","content": AGENT_SYS_BASE + "\n" + ctx},
        {"role":"user",  "content": text}
    ]
    reply, model, _ = route_ai_call(messages, task_type="chat")
    with neural_lock:
        neural_state["last_cmd"]   = text
        neural_state["last_reply"] = reply
        neural_state["conv_state"] = "idle"
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
    result = call_gemini(prompt, image_base64=img_b64)
    return jsonify(result)


@ai.route("/api/neural/activate", methods=["POST","OPTIONS"])
@api_errors
def neural_activate():
    if request.method == "OPTIONS": return "", 204
    with neural_lock:
        neural_state["active"]     = True
        neural_state["conv_state"] = "idle"
    push_system_event("neural","Neural Mode activated, Sir.")
    return jsonify({"ok": True, "active": True})


@ai.route("/api/neural/deactivate", methods=["POST","OPTIONS"])
@api_errors
def neural_deactivate():
    if request.method == "OPTIONS": return "", 204
    with neural_lock:
        neural_state["active"]     = False
        neural_state["conv_state"] = "idle"
    return jsonify({"ok": True, "active": False})


@ai.route("/api/neural/status", methods=["GET"])
@api_errors
def neural_status():
    with neural_lock:
        snap = {k: v for k, v in neural_state.items() if k != "event_queue"}
    return jsonify(snap)


@ai.route("/api/neural/silence", methods=["POST","OPTIONS"])
@api_errors
def neural_silence():
    if request.method == "OPTIONS": return "", 204
    minutes = (request.get_json(silent=True) or {}).get("minutes", 30)
    heartbeat_cfg["silence_until"] = time.time() + minutes * 60
    return jsonify({"ok": True, "silenced_for_minutes": minutes})


@ai.route("/api/neural/conv_state", methods=["POST","OPTIONS"])
@api_errors
def neural_conv_state():
    if request.method == "OPTIONS": return "", 204
    state = (request.get_json(silent=True) or {}).get("state","idle")
    with neural_lock:
        neural_state["conv_state"] = state
    return jsonify({"ok": True, "conv_state": state})


@ai.route("/api/speak", methods=["POST","OPTIONS"])
@api_errors
def speak():
    if request.method == "OPTIONS": return "", 204
    data = request.get_json(silent=True) or {}
    msg  = (data.get("message") or data.get("text") or "").strip()
    if not msg:
        return jsonify({"error": "No message"}), 400
    send_os_notification("J.A.R.V.I.S", msg)
    return jsonify({"ok": True})


@ai.route("/api/events/poll", methods=["GET"])
@api_errors
def events_poll():
    with neural_lock:
        events = list(neural_state.get("event_queue",[]))
        neural_state["event_queue"] = []
    with heartbeat_lock:
        hb = list(heartbeat_queue)
        heartbeat_queue.clear()
    return jsonify({"events": events, "heartbeat": hb, "count": len(events)+len(hb)})


@ai.route("/api/system/events", methods=["GET"])
@api_errors
def system_events():
    rows = db_read("SELECT * FROM events ORDER BY id DESC LIMIT 50")
    return jsonify({"events": rows, "count": len(rows)})
