"""Tool registry and server-side cloud integrations."""
from app.tools.registry import Tool, REGISTRY, register, llm_schemas, get_tool
from app.tools import server_tools as _server_tools  # noqa: F401
from app.tools import device_tools as _device_tools  # noqa: F401
from app.tools.server_tools import tool_get_weather, tool_web_search, tool_search_memory

__all__ = [
    "Tool",
    "REGISTRY",
    "register",
    "llm_schemas",
    "get_tool",
    "tool_get_weather",
    "tool_web_search",
    "tool_search_memory",
]
