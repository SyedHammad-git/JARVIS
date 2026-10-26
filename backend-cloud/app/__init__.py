"""Backend application factory for the cloud-hosted JARVIS service."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask


log = logging.getLogger("jarvis.backend")


def load_environment() -> None:
    if os.environ.get("JARVIS_SKIP_DOTENV") == "1":
        return
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env", override=False)
    config_module = sys.modules.get("app.config")
    if config_module is not None:
        config_module.refresh_api_keys()


def create_app(
    testing: bool = False,
    config_object: dict[str, Any] | None = None,
    bind_host: str | None = None,
) -> Flask:
    """Create and configure the Flask app, starting workers only for runtime use."""
    load_environment()

    from app.security import (
        configure_proxy,
        configure_session,
        configured_cors_origins,
        configured_auth_mode,
        install_api_security,
        validate_production_config,
    )

    configured_auth_mode()
    validate_production_config()
    production = os.environ.get("JARVIS_ENV", "development").lower() == "production"
    if not testing and not production:
        from app.bind import resolve_bind_host

        bind_host = resolve_bind_host(bind_host)
    elif not testing:
        bind_host = f"gunicorn-managed:0.0.0.0:{os.environ.get('PORT', 'unset')}"

    from app.db import init_db
    from app.extensions import socketio

    init_db()

    app = Flask(
        __name__,
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    configure_proxy(app)
    configure_session(app)

    app.config.update(
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,
        TESTING=testing,
        JARVIS_ENV=os.environ.get("JARVIS_ENV", "development").strip().lower(),
        LANDING_URL=os.environ.get("LANDING_URL", "").strip(),
    )
    if bind_host is not None:
        app.config["JARVIS_HOST"] = bind_host

    if config_object:
        app.config.update(config_object)

    from app.config import FLASK_SECRET
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = FLASK_SECRET

    from app.devices.gateway import register_namespace
    from app.devices.http import devices_bp
    from app.routes.auth_routes import auth
    from app.routes.ai_routes import ai
    from app.routes.core_routes import core
    from app.routes.key_routes import keys_bp
    from app.routes.data_routes import data
    from app.routes.iot_routes import iot
    from app.routes.system_routes import system
    from app.routes.webhook_routes import webhooks
    from flask import jsonify

    for blueprint in (auth, core, ai, system, data, iot, devices_bp, keys_bp, webhooks):
        app.register_blueprint(blueprint)

    socketio.init_app(app)
    register_namespace(socketio)
    install_api_security(app)

    from flask_cors import CORS

    cors_origins = configured_cors_origins()
    CORS(app, origins=cors_origins, supports_credentials=True)

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Endpoint not found", "code": 404}), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify({"error": "Method not allowed", "code": 405}), 405

    @app.errorhandler(500)
    def internal_error(error):
        log.error("Unhandled 500: %s", error)
        return jsonify({"error": "Internal server error", "code": 500}), 500

    if not app.config["TESTING"]:
        from app import config as backend_config
        from app.db import DB_BACKEND
        from app import monitor, neural
        from app.vision.snapshots import cleanup_snapshots

        auth_enabled = bool(app.config.get("AUTH_ENABLED"))
        log.warning(
            "STARTUP SELF-CHECK provider_key_presence groq=%s gemini=%s openrouter=%s weather=%s; "
            "db_backend=%s bind_host=%s auth_enabled=%s",
            bool(backend_config.get_api_key("GROQ_KEY")),
            bool(backend_config.get_api_key("GEMINI_KEY")),
            bool(backend_config.get_api_key("OPENROUTER_KEY")),
            bool(backend_config.get_api_key("WEATHER_KEY")),
            DB_BACKEND,
            bind_host,
            "yes" if auth_enabled else "no",
        )
        if not auth_enabled:
            log.warning("SECURITY WARNING: API authentication is currently disabled")
        cleanup_snapshots()
        monitor.start_background_threads()
        neural.start_background_threads()

    return app
