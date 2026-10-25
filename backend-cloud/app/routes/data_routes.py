"""
J.A.R.V.I.S v17.M — Data Routes Blueprint
FIXED: notes INSERT uses correct columns (created/updated), not timestamp
"""
import datetime, logging
from flask import Blueprint, g, jsonify, request
from app.db import db_read, db_write, db_scalar, ts
from app.memory import get_facts, learn_fact, forget_fact, get_context
from app.neural import invalidate_alarm_cache
from app.auth import add_alert
from app.error_utils import api_errors

log  = logging.getLogger("jarvis.routes.data")
data = Blueprint("data", __name__)


# ── Memory ────────────────────────────────────────────────────────
@data.route("/api/memory/facts", methods=["GET"])
@api_errors
def memory_facts():
    category = request.args.get("category","")
    rows     = get_facts(category, owner_username=g.current_user["username"])
    return jsonify({"facts": rows, "count": len(rows), "category": category})

@data.route("/api/memory/learn", methods=["POST","OPTIONS"])
@api_errors
def memory_learn():
    if request.method == "OPTIONS": return "", 204
    body     = request.get_json(silent=True) or {}
    fact     = (body.get("fact") or "").strip()
    category = (body.get("category") or "general").strip()
    source   = (body.get("source")   or "manual").strip()
    if not fact: return jsonify({"error":"No fact provided"}), 400
    return jsonify({"ok": True, "result": learn_fact(
        fact, category=category, source=source, owner_username=g.current_user["username"]
    )})

@data.route("/api/memory/forget", methods=["POST","OPTIONS"])
@api_errors
def memory_forget():
    if request.method == "OPTIONS": return "", 204
    fact_id = (request.get_json(silent=True) or {}).get("id")
    if not fact_id: return jsonify({"error":"No id provided"}), 400
    forget_fact(fact_id, owner_username=g.current_user["username"])
    return jsonify({"ok": True, "message":"Fact removed, Sir."})

@data.route("/api/memory/context", methods=["GET"])
@api_errors
def memory_context():
    return jsonify({"ok": True, "context": get_context(g.current_user["username"]), "ts": ts()})


# ── Notes ─────────────────────────────────────────────────────────
@data.route("/api/notes", methods=["GET","POST","OPTIONS"])
@api_errors
def notes():
    if request.method == "OPTIONS": return "", 204
    if request.method == "POST":
        body    = request.get_json(silent=True) or {}
        content = (body.get("content") or body.get("text") or "").strip()
        title   = (body.get("title") or "").strip()
        if not content: return jsonify({"error":"No content"}), 400
        now = ts()
        # ✅ FIX: correct column names (created + updated), not timestamp
        db_write(
            "INSERT INTO notes(owner_username,title,content,created_at,updated_at) VALUES(?,?,?,?,?)",
            (g.current_user["username"], title, content, now, now)
        )
        add_alert(f"Note saved: {title or content[:30]}", owner_username=g.current_user["username"])
        return jsonify({"ok": True, "message":"Note saved, Sir."})
    rows = db_read("SELECT * FROM notes WHERE owner_username=? ORDER BY id DESC LIMIT 100",
                   (g.current_user["username"],))
    return jsonify({"notes": rows, "count": len(rows)})


# ── Alarms ────────────────────────────────────────────────────────
@data.route("/api/alarms", methods=["GET","POST","OPTIONS"])
@api_errors
def alarms():
    if request.method == "OPTIONS": return "", 204
    if request.method == "POST":
        import datetime as _dt
        body   = request.get_json(silent=True) or {}
        time_  = (body.get("time") or "").strip()
        label  = (body.get("label") or body.get("name") or "Reminder").strip()
        repeat = (body.get("repeat") or "once").strip()
        if not time_:
            return jsonify({"error": "No time provided. Use HH:MM format"}), 400
        # Normalize to HH:MM
        for fmt in ("%H:%M", "%I:%M %p", "%H.%M"):
            try:
                time_ = _dt.datetime.strptime(time_, fmt).strftime("%H:%M")
                break
            except ValueError:
                pass
        saved = db_write(
            "INSERT INTO alarms(owner_username,time,label,repeat,active,created_at,status) VALUES(?,?,?, ?,1,?,?)",
            (g.current_user["username"], time_, label, repeat, ts(), "pending")
        )
        if saved:
            invalidate_alarm_cache(g.current_user["username"])
        add_alert(f"Alarm set: {label} @ {time_}", owner_username=g.current_user["username"])
        return jsonify({"ok": True, "message": f"Alarm set for {time_}, Sir."})
    rows = db_read("SELECT * FROM alarms WHERE owner_username=? AND active=1 ORDER BY time ASC",
                   (g.current_user["username"],))
    return jsonify({"alarms": rows, "count": len(rows)})
@data.route("/api/alarms/cancel/<int:alarm_id>", methods=["POST","OPTIONS"])
@api_errors
def alarm_cancel(alarm_id):
    if request.method == "OPTIONS": return "", 204
    changed = db_write("UPDATE alarms SET active=0 WHERE id=? AND owner_username=?",
                       (alarm_id, g.current_user["username"]))
    if changed:
        invalidate_alarm_cache(g.current_user["username"])
    return jsonify({"ok": True, "message":"Alarm cancelled, Sir."})

@data.route("/api/alarms/upcoming", methods=["GET"])
@api_errors
def alarms_upcoming():
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = db_read(
        "SELECT * FROM alarms WHERE owner_username=? AND active=1 AND time>=? ORDER BY time ASC LIMIT 10",
        (g.current_user["username"], now)
    )
    return jsonify({"upcoming": rows, "count": len(rows)})


# ── DB inspector ──────────────────────────────────────────────────
@data.route("/api/db/history", methods=["GET"])
@api_errors
def db_history():
    session_id = request.args.get("session_id","default")
    limit      = min(int(request.args.get("limit",50)), 200)
    rows       = db_read(
        "SELECT * FROM conversations WHERE owner_username=? AND session_id=? ORDER BY id DESC LIMIT ?",
        (g.current_user["username"], session_id, limit)
    )
    return jsonify({"history": list(reversed(rows)), "count": len(rows)})

@data.route("/api/db/stats", methods=["GET"])
@api_errors
def db_stats():
    return jsonify({
        "conversations": db_scalar("SELECT COUNT(*) FROM conversations WHERE owner_username=?",
                                   (g.current_user["username"],)) or 0,
        "memory_facts":  db_scalar("SELECT COUNT(*) FROM memory_facts WHERE owner_username=?",
                                   (g.current_user["username"],)) or 0,
        "events":        db_scalar("SELECT COUNT(*) FROM events WHERE owner_username=?",
                                   (g.current_user["username"],)) or 0,
        "notes":         db_scalar("SELECT COUNT(*) FROM notes WHERE owner_username=?",
                                   (g.current_user["username"],)) or 0,
        "alarms":        db_scalar("SELECT COUNT(*) FROM alarms WHERE owner_username=? AND active=1",
                                   (g.current_user["username"],)) or 0,
        "monitors":      db_scalar("SELECT COUNT(*) FROM monitors WHERE owner_username=? AND active=1",
                                   (g.current_user["username"],)) or 0,
        "command_log":   db_scalar("SELECT COUNT(*) FROM command_log WHERE owner_username=?",
                                   (g.current_user["username"],)) or 0,
    })

@data.route("/api/db/events", methods=["GET"])
@api_errors
def db_events():
    limit = min(int(request.args.get("limit",100)), 500)
    rows  = db_read("SELECT * FROM events WHERE owner_username=? ORDER BY id DESC LIMIT ?",
                    (g.current_user["username"], limit))
    return jsonify({"events": rows, "count": len(rows)})
