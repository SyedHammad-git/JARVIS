"""Compatibility alias for the canonical database module in :mod:`app.db`."""

from __future__ import annotations

import sys

from app import db as _database

sys.modules[__name__] = _database
sys.modules["database"] = _database
