"""
J.A.R.V.I.S v17.M — API error handling (TASK-011)

Most of the 73 routes across routes/*.py had zero try/except of their own,
so any failure fell straight through to server.py's global
`@app.errorhandler(Exception)` and came back as the same generic
`{"error": "An unexpected error occurred", "code": 500}` — no matter
whether the real cause was a malformed request body, a dead upstream AI
provider, a missing file, or a denied system permission.

`@api_errors` wraps a route so the *anticipated, common* failure families
get a specific, JARVIS-toned JSON response with the right status code.
Anything NOT covered here still propagates to server.py's global handler
unchanged — that handler stays the true last-resort safety net (and keeps
doing its own full-traceback logging), it just stops being the primary
path for everyday failures.
"""
import functools
import logging
import sqlite3
import subprocess
import threading
import time

import psutil
import requests
from flask import jsonify

log = logging.getLogger("jarvis.errors")


class CircuitBreaker:
    """Consecutive-failure circuit breaker for an external service.

    Opens (blocks further attempts) after `threshold` consecutive failures,
    for `cooldown` seconds — so a known-down service doesn't get hit again
    on every single request while it's out. After the cooldown, one trial
    attempt is allowed through: a success fully resets the breaker, a
    failed trial re-arms the cooldown. Thread-safe.

    Deliberately gates on the cooldown timer alone, not a separate
    'is_ok' flag — a flag that's only cleared by a success, when nothing
    is calling the service to produce that success, means a single
    failure could lock the breaker open forever. (Same bug shape found
    and fixed in ai_engine.py's Groq circuit breaker — same fix here.)
    """
    def __init__(self, threshold: int = 3, cooldown: float = 60):
        self.threshold = threshold
        self.cooldown  = cooldown
        self._fails           = 0
        self._cooldown_until  = 0.0
        self._lock            = threading.Lock()

    def available(self) -> bool:
        with self._lock:
            return time.time() >= self._cooldown_until

    def record_success(self):
        with self._lock:
            self._fails = 0
            self._cooldown_until = 0.0

    def record_failure(self):
        with self._lock:
            self._fails += 1
            if self._fails >= self.threshold:
                self._cooldown_until = time.time() + self.cooldown


def classify_exception(e: Exception):
    """Map an exception to a short, lowercase, JARVIS-toned phrase (no
    trailing punctuation — designed to slot after "Sir — ") plus an
    HTTP-style status code. Returns (None, 500) for anything unclassified,
    so callers can decide what to do (re-raise for routes, fall back to a
    generic phrase for tool results).

    Used by `api_errors` below (TASK-011, routes) and by
    `agent.py::execute_tool()` (TASK-030, tool-call results) so the same
    kind of failure gets the same phrasing everywhere in the app, not two
    different vocabularies depending on which layer caught it."""
    if isinstance(e, (KeyError, TypeError, ValueError)):
        return "the input wasn't valid", 400
    if isinstance(e, requests.exceptions.Timeout):
        return "the request timed out", 504
    if isinstance(e, requests.exceptions.RequestException):
        return "an external service was unreachable", 502
    if isinstance(e, PermissionError):
        return "permission was denied", 403
    if isinstance(e, (FileNotFoundError, IsADirectoryError)):
        return "the file couldn't be found", 404
    if isinstance(e, psutil.Error):
        return "that process is no longer available", 404
    if isinstance(e, subprocess.SubprocessError):
        return "the system command didn't complete", 500
    if isinstance(e, sqlite3.Error):
        return "a storage error occurred", 503
    return None, 500


def api_errors(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)

        except (KeyError, TypeError, ValueError) as e:
            log.warning("%s: malformed request — %s", fn.__name__, e)
            return jsonify({
                "error": "Invalid request, Sir — a required value was missing or malformed.",
                "code": 400,
            }), 400

        except requests.exceptions.Timeout:
            log.warning("%s: upstream timeout", fn.__name__)
            return jsonify({
                "error": "That request is taking longer than expected, Sir — the upstream service timed out.",
                "code": 504,
            }), 504

        except requests.exceptions.RequestException as e:
            log.warning("%s: upstream unreachable — %s", fn.__name__, e)
            return jsonify({
                "error": "I'm unable to reach an external service at the moment, Sir.",
                "code": 502,
            }), 502

        except PermissionError as e:
            log.warning("%s: permission denied — %s", fn.__name__, e)
            return jsonify({
                "error": "Access to that resource was denied, Sir.",
                "code": 403,
            }), 403

        except (FileNotFoundError, IsADirectoryError) as e:
            log.warning("%s: file not found — %s", fn.__name__, e)
            return jsonify({
                "error": "I couldn't locate that file, Sir.",
                "code": 404,
            }), 404

        except psutil.Error as e:
            log.warning("%s: process error — %s", fn.__name__, e)
            return jsonify({
                "error": "That process is no longer available, Sir.",
                "code": 404,
            }), 404

        except subprocess.SubprocessError as e:
            log.error("%s: system command failed — %s", fn.__name__, e)
            return jsonify({
                "error": "That system command didn't complete successfully, Sir.",
                "code": 500,
            }), 500

        except sqlite3.Error as e:
            # Defense-in-depth: database.py already catches its own errors
            # internally and returns safe defaults, so this should rarely
            # fire — but if a raw sqlite3 call is ever added at route level,
            # it gets a real answer instead of a bare 500.
            log.error("%s: database error — %s", fn.__name__, e)
            return jsonify({
                "error": "I'm having trouble reaching storage, Sir. Please try again.",
                "code": 503,
            }), 503

        # Anything else: let it propagate to server.py's global
        # @app.errorhandler(Exception) — the true last resort, unchanged.

    return wrapped
