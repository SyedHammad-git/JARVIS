"""Server-side heartbeat, Discord, and weather routes."""
from flask import Blueprint, jsonify, request

from app.config import discord_cfg, heartbeat_cfg, heartbeat_queue, heartbeat_lock
from app.db import cfg_set, db_read
from app.error_utils import api_errors
from app.notifications import send_discord_alert
from app.tools.server_tools import tool_get_weather

system = Blueprint("system", __name__)


@system.route("/api/heartbeat/status", methods=["GET", "POST", "OPTIONS"])
@api_errors
def heartbeat_status():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if "enabled" in body:
            heartbeat_cfg["enabled"] = bool(body["enabled"])
        with heartbeat_lock:
            pending = list(heartbeat_queue)
        return jsonify({"ok": True, "config": heartbeat_cfg, "pending": pending})
    with heartbeat_lock:
        pending = list(heartbeat_queue)
    return jsonify({
        "enabled": heartbeat_cfg.get("enabled"),
        "interval_min": heartbeat_cfg.get("interval", 30),
        "last_run": heartbeat_cfg.get("last_run", 0),
        "silence_until": heartbeat_cfg.get("silence_until", 0),
        "pending": pending,
        "pending_count": len(pending),
    })


@system.route("/api/heartbeat/poll", methods=["GET"])
@api_errors
def heartbeat_poll():
    with heartbeat_lock:
        messages = list(heartbeat_queue)
        heartbeat_queue.clear()
    return jsonify({"messages": messages, "count": len(messages)})


@system.route("/api/heartbeat/config", methods=["GET", "POST", "OPTIONS"])
@api_errors
def heartbeat_config_route():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        for key in ("enabled", "interval", "coding_break_mins"):
            if key in body:
                heartbeat_cfg[key] = body[key]
        return jsonify({"ok": True, "config": heartbeat_cfg})
    return jsonify(heartbeat_cfg)


@system.route("/api/heartbeat/log", methods=["GET"])
@api_errors
def heartbeat_log():
    rows = db_read(
        "SELECT * FROM events WHERE type='heartbeat' ORDER BY id DESC LIMIT 50"
    )
    return jsonify({"log": rows, "count": len(rows)})


@system.route("/api/discord/config", methods=["GET", "POST", "OPTIONS"])
@api_errors
def discord_config():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if "webhook_url" in body:
            discord_cfg["webhook_url"] = body["webhook_url"]
            cfg_set("discord_webhook_url", body["webhook_url"])
        if "enabled" in body:
            discord_cfg["enabled"] = bool(body["enabled"])
            cfg_set("discord_enabled", "true" if body["enabled"] else "false")
        return jsonify({"ok": True})
    return jsonify({
        "webhook_configured": bool(discord_cfg.get("webhook_url", "")),
        "enabled": discord_cfg.get("enabled"),
    })


@system.route("/api/discord/test", methods=["POST", "OPTIONS"])
@api_errors
def discord_test():
    if request.method == "OPTIONS":
        return "", 204
    return jsonify({"ok": send_discord_alert("JARVIS Discord test — connection successful!")})


@system.route("/api/discord/send", methods=["POST", "OPTIONS"])
@api_errors
def discord_send():
    if request.method == "OPTIONS":
        return "", 204
    message = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not message:
        return jsonify({"error": "No message"}), 400
    return jsonify({"ok": send_discord_alert(message)})


@system.route("/api/weather", methods=["GET"])
@api_errors
def weather():
    city = request.args.get("city", "Faisalabad")
    return jsonify({"weather": tool_get_weather(city), "city": city})
