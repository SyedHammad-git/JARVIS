"""
J.A.R.V.I.S — Tool registry.

Every tool declares where it runs (server | device) and a risk level.
llm_schemas(device_online) returns OpenAI-style function schemas and hides
device tools when the Electron client is offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

log_name = "jarvis.tools"

REGISTRY: dict[str, "Tool"] = {}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    where: str  # "server" | "device"
    risk: str   # "low" | "medium" | "high"
    handler: Optional[Callable] = None
    extra: dict = field(default_factory=dict)


def register(tool: Tool) -> Tool:
    if tool.where not in ("server", "device"):
        raise ValueError(f"Tool {tool.name}: where must be 'server' or 'device'")
    if tool.risk not in ("low", "medium", "high"):
        raise ValueError(f"Tool {tool.name}: risk must be low|medium|high")
    if tool.name in REGISTRY:
        raise ValueError(f"Duplicate tool registration: {tool.name}")
    REGISTRY[tool.name] = tool
    return tool


def get_tool(name: str) -> Optional[Tool]:
    return REGISTRY.get(name)


def llm_schemas(device_online: bool | None = None, device_id: str | None = None) -> list:
    """OpenAI-style tool schemas. Device tools are omitted when offline."""
    if device_online is None:
        try:
            from app.config import DEVICE_ID
            from app.devices.gateway import is_online
            device_online = is_online(device_id or DEVICE_ID)
        except Exception:
            device_online = False
    schemas = []
    for tool in REGISTRY.values():
        if tool.where == "device" and not device_online:
            continue
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        })
    return schemas
