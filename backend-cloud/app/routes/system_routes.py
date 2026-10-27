"""Server-side heartbeat, Discord, and weather routes."""
from flask import Blueprint, g, jsonify, request

from app.db import db_read, db_write, ts
from app.error_utils import api_errors
from app.neural import (
    get_heartbeat_config, get_heartbeat_queue, update_heartbeat_config,
)
from app.notifications import get_discord_settings, send_discord_alert
from app.tools.server_tools import tool_get_weather

system = Blueprint("system", __name__)


@system.route("/api/heartbeat/status", methods=["GET", "POST", "OPTIONS"])
@api_errors
def heartbeat_status():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        updates = {
            key: body[key] for key in ("enabled", "interval", "coding_break_mins")
            if key in body
        }
        if "enabled" in updates:
            updates["enabled"] = bool(updates["enabled"])
        config = update_heartbeat_config(g.current_user["username"], updates)
        pending = get_heartbeat_queue(g.current_user["username"])
        return jsonify({"ok": True, "config": config, "pending": pending})
    config = get_heartbeat_config(g.current_user["username"])
    pending = get_heartbeat_queue(g.current_user["username"])
    return jsonify({
        "enabled": config.get("enabled"),
        "interval_min": config.get("interval", 30),
        "last_run": config.get("last_run", 0),
        "silence_until": config.get("silence_until", 0),
        "pending": pending,
        "pending_count": len(pending),
    })


@system.route("/api/heartbeat/poll", methods=["GET"])
@api_errors
def heartbeat_poll():
    messages = get_heartbeat_queue(g.current_user["username"], clear=True)
    return jsonify({"messages": messages, "count": len(messages)})


@system.route("/api/heartbeat/config", methods=["GET", "POST", "OPTIONS"])
@api_errors
def heartbeat_config_route():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        updates = {
            key: body[key] for key in ("enabled", "interval", "coding_break_mins")
            if key in body
        }
        if "enabled" in updates:
            updates["enabled"] = bool(updates["enabled"])
        return jsonify({
            "ok": True,
            "config": update_heartbeat_config(g.current_user["username"], updates),
        })
    return jsonify(get_heartbeat_config(g.current_user["username"]))


@system.route("/api/heartbeat/log", methods=["GET"])
@api_errors
def heartbeat_log():
    rows = db_read(
        "SELECT * FROM events WHERE owner_username=? AND type='heartbeat' ORDER BY id DESC LIMIT 50",
        (g.current_user["username"],),
    )
    return jsonify({"log": rows, "count": len(rows)})


@system.route("/api/discord/config", methods=["GET", "POST", "OPTIONS"])
@api_errors
def discord_config():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        owner = g.current_user["username"]
        settings = get_discord_settings(owner)
        webhook_url = settings["webhook_url"]
        enabled = settings["enabled"]
        if "webhook_url" in body:
            value = body["webhook_url"]
            if not isinstance(value, str) or (value and not value.startswith("https://discord.com/api/webhooks/")):
                return jsonify({"ok": False, "error": "invalid_webhook_url"}), 400
            webhook_url = value.strip()
        if "enabled" in body:
            enabled = bool(body["enabled"])
        saved = db_write(
            "INSERT INTO discord_settings(owner_username,webhook_url,enabled,updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(owner_username) DO UPDATE SET "
            "webhook_url=excluded.webhook_url,enabled=excluded.enabled,updated_at=excluded.updated_at",
            (owner, webhook_url, int(enabled), ts()),
        )
        return jsonify({"ok": bool(saved)})
    settings = get_discord_settings(g.current_user["username"])
    return jsonify({
        "webhook_configured": bool(settings["webhook_url"]),
        "enabled": settings["enabled"],
    })


@system.route("/api/discord/test", methods=["POST", "OPTIONS"])
@api_errors
def discord_test():
    if request.method == "OPTIONS":
        return "", 204
    return jsonify({"ok": send_discord_alert(
        "JARVIS Discord test — connection successful!",
        owner_username=g.current_user["username"],
    )})


@system.route("/api/discord/send", methods=["POST", "OPTIONS"])
@api_errors
def discord_send():
    if request.method == "OPTIONS":
        return "", 204
    message = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not message:
        return jsonify({"error": "No message"}), 400
    return jsonify({"ok": send_discord_alert(message, owner_username=g.current_user["username"] )})


@system.route("/api/weather", methods=["GET"])
@api_errors
def weather():
    city = request.args.get("city", "Faisalabad")
    return jsonify({"weather": tool_get_weather(city), "city": city})
