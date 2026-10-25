
from flask import Flask

from app.routes.core_routes import core

def test_desktop_page_is_served_as_html():
    app = Flask(__name__)
    app.register_blueprint(core)

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b"JARVIS" in response.data
    assert not response.is_json


def test_mobile_page_is_served_as_html():
    app = Flask(__name__)
    app.register_blueprint(core)

    response = app.test_client().get("/mobile")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b"JARVIS" in response.data
    assert not response.is_json
