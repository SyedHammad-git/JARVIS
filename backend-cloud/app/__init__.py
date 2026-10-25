"""Backend application factory for the cloud-hosted JARVIS service."""

from __future__ import annotations

import logging
import os
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


def create_app(testing: bool = False, config_object: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask app, starting workers only for runtime use."""
    load_environment()

    from app.db import init_db
    from app.extensions import socketio

    init_db()

    app = Flask(
        __name__,
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )

    app.config.update(JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=32 * 1024 * 1024, TESTING=testing)

    if config_object:
        app.config.update(config_object)

    from app.config import FLASK_SECRET
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = FLASK_SECRET

    from app.devices.gateway import register_namespace
    from app.devices.http import devices_bp
    from app.routes.ai_routes import ai
    from app.routes.core_routes import core
    from app.routes.data_routes import data
    from app.routes.iot_routes import iot
    from app.routes.system_routes import system
    from flask import jsonify

    for blueprint in (core, ai, system, data, iot, devices_bp):
        app.register_blueprint(blueprint)

    socketio.init_app(app)
    register_namespace(socketio)

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
        from app import monitor, neural
        from app.vision.snapshots import cleanup_snapshots

        cleanup_snapshots()
        monitor.start_background_threads()
        neural.start_background_threads()

    return app
