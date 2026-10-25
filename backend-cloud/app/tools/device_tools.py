"""Schemas for actions executed only by a paired desktop client."""
from __future__ import annotations

from app.tools.registry import Tool, register


_DEVICE_SCHEMAS = (
    Tool(
        name="open_app",
        description="Open an allowlisted application on the paired PC.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["notepad", "calculator", "explorer", "paint"],
                }
            },
            "required": ["target"],
        },
        where="device",
        risk="medium",
    ),
    Tool(
        name="open_url",
        description="Open an HTTP or HTTPS URL in the paired PC's default browser.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        where="device",
        risk="medium",
    ),
    Tool(
        name="notify",
        description="Show a notification on the paired PC.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["title", "body"],
        },
        where="device",
        risk="low",
    ),
    Tool(
        name="lock_screen",
        description="Lock the paired PC screen.",
        parameters={"type": "object", "properties": {}},
        where="device",
        risk="high",
    ),
    Tool(
        name="system_stats",
        description="Get system status from the paired PC.",
        parameters={"type": "object", "properties": {}},
        where="device",
        risk="low",
    ),
    Tool(
        name="take_snapshot",
        description="Take an on-demand camera snapshot on the paired PC.",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "width": {"type": "integer", "minimum": 160, "maximum": 1920},
                "quality": {"type": "number", "minimum": 0.1, "maximum": 0.95},
            },
        },
        where="device",
        risk="medium",
    ),
)

for _tool in _DEVICE_SCHEMAS:
    register(_tool)
