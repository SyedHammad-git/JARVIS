"""Gunicorn configuration for the Flask-Socket.IO gthread deployment."""
from __future__ import annotations

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "gthread"
workers = 1
threads = 100
timeout = 120
graceful_timeout = 30
keepalive = 75
accesslog = "-"
errorlog = "-"
capture_output = True
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
