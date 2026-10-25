"""Backend application factory for the cloud-hosted JARVIS service."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from flask import Flask

def create_app(testing: bool = False, config_object: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask app, starting workers only for runtime use."""
    app_dir = str(Path(__file__).resolve().parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    repo_dir = str(Path(__file__).resolve().parents[2])
    if repo_dir not in sys.path:
        sys.path.insert(0, repo_dir)

    from extensions import socketio
    import database
    database.init_db()

    app = Flask(__name__, static_folder="static")

    app.config.update(JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=32 * 1024 * 1024, TESTING=testing)

    if config_object:
        app.config.update(config_object)

    import config as backend_config
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = backend_config.FLASK_SECRET

    from .routes.core_routes import core
    from .routes.ai_routes import ai
    from .routes.system_routes import system
    from .routes.data_routes import data
    from .routes.iot_routes import iot
    from .devices.http import devices_bp
    from devices.gateway import register_namespace
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
        import monitor
        import neural
        from vision.snapshots import cleanup_snapshots

        cleanup_snapshots()
        monitor.start_background_threads()
        neural.start_background_threads()

    return app


log = logging.getLogger("jarvis.backend")
