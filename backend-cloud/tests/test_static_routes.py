
from flask import Flask

from app.routes.core_routes import core

def test_development_serves_legacy_desktop_page():
    app = Flask(__name__)
    app.config["JARVIS_ENV"] = "development"
    app.register_blueprint(core)

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b"JARVIS" in response.data
    assert not response.is_json


def test_development_serves_legacy_mobile_page():
    app = Flask(__name__)
    app.config["JARVIS_ENV"] = "development"
    app.register_blueprint(core)

    response = app.test_client().get("/mobile")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b"JARVIS" in response.data
    assert not response.is_json


def test_production_redirects_legacy_desktop_route_to_landing():
    app = Flask(__name__)
    app.config.update(JARVIS_ENV="production", LANDING_URL="https://jarvis.example.test")
    app.register_blueprint(core)

    response = app.test_client().get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "https://jarvis.example.test"


def test_production_redirects_legacy_mobile_route_to_landing():
    app = Flask(__name__)
    app.config.update(JARVIS_ENV="production", LANDING_URL="https://jarvis.example.test")
    app.register_blueprint(core)

    response = app.test_client().get("/mobile", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "https://jarvis.example.test"
