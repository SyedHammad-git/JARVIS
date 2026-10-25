"""Compatibility wrapper for legacy flat imports.

The database implementation now lives in the package tree under app.db.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_module_path = Path(__file__).resolve().parent / "db" / "__init__.py"
_spec = importlib.util.spec_from_file_location("jarvis_compat_database", _module_path)
if _spec is None or _spec.loader is None:
	raise ImportError(f"Could not load database implementation from {_module_path}")

_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
sys.modules["database"] = _module

globals().update(_module.__dict__)

for _name in dir(_module):
	if _name.startswith("__") and _name not in {"__all__", "__doc__", "__name__"}:
		continue
	globals()[_name] = getattr(_module, _name)

__all__ = getattr(_module, "__all__", [name for name in globals() if not name.startswith("_")])
