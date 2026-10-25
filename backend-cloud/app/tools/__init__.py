"""J.A.R.V.I.S tool package — registry + server/device implementations."""
from tools.registry import Tool, REGISTRY, register, llm_schemas, get_tool
from tools import server_tools as _server_tools  # noqa: F401 — registers tools
from tools import device_tools as _device_tools  # noqa: F401 — registers tools

from tools.server_tools import tool_get_weather, tool_web_search, tool_search_memory
from tools.device_tools import (
    APP_REGISTRY, APP_URL_REGISTRY, PYAUTOGUI_OK,
    tool_open_app, tool_open_url, tool_file_find, tool_file_read,
    tool_get_processes, tool_kill_process, tool_get_system_status,
    tool_take_screenshot, tool_describe_screen, tool_control_volume,
    tool_type_text, tool_get_clipboard, tool_set_clipboard,
    tool_create_folder, tool_system_action,
)

AGENT_TOOLS = llm_schemas(device_online=True)

TOOL_REG = {}
for _name, _tool in REGISTRY.items():
    _fn = _tool.handler if _tool.where == "server" else _tool.local_impl
    TOOL_REG[_name] = (lambda a, f=_fn: f(a)) if _fn else (lambda a: "unavailable")

__all__ = [
    "Tool", "REGISTRY", "register", "llm_schemas", "get_tool",
    "AGENT_TOOLS", "TOOL_REG",
    "APP_REGISTRY", "APP_URL_REGISTRY", "PYAUTOGUI_OK",
    "tool_get_weather", "tool_web_search", "tool_search_memory",
    "tool_open_app", "tool_open_url", "tool_file_find", "tool_file_read",
    "tool_get_processes", "tool_kill_process", "tool_get_system_status",
    "tool_take_screenshot", "tool_describe_screen", "tool_control_volume",
    "tool_type_text", "tool_get_clipboard", "tool_set_clipboard",
    "tool_create_folder", "tool_system_action",
]
