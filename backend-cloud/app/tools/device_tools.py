"""
Device tools — local OS actions.

`local_impl` runs only when EXECUTION_MODE=local (this PC). Remote dispatch
is a stub until the Electron client (Step 4).
No arbitrary shell strings. No shell=True.
"""
from __future__ import annotations

import logging
import base64
import math
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import psutil

try:
    import pyautogui
    PYAUTOGUI_OK = True
except Exception:
    pyautogui = None
    PYAUTOGUI_OK = False
    print("[TOOLS] ⚠  pyautogui unavailable — GUI tools disabled")

from config import CLIP_OK, pyperclip, _server_start
from database import HOME, DATA_DIR
from auth import safety_check, add_alert
from ai_engine import call_gemini, groq_as_manager
from error_utils import classify_exception
from tools.registry import Tool, register

log = logging.getLogger("jarvis.tools")

APP_REGISTRY = {
    "chrome": "chrome", "google chrome": "chrome",
    "vscode": "code", "code": "code", "visual studio code": "code",
    "word": "winword", "microsoft word": "winword",
    "excel": "excel", "microsoft excel": "excel",
    "powerpoint": "powerpnt", "outlook": "outlook",
    "spotify": "spotify", "calculator": "calc", "calc": "calc",
    "notepad": "notepad", "task manager": "taskmgr",
    "file explorer": "explorer", "explorer": "explorer",
    "this pc": "explorer.exe",
    "documents": "shell:Personal", "downloads": "shell:Downloads",
    "desktop": "shell:Desktop", "paint": "mspaint",
    "cmd": "cmd", "powershell": "powershell", "edge": "msedge", "firefox": "firefox",
    "teams": "teams", "zoom": "zoom", "settings": "ms-settings:",
}
APP_URL_REGISTRY = {
    "youtube": "https://youtube.com", "google": "https://google.com",
    "whatsapp": "https://web.whatsapp.com", "github": "https://github.com",
    "linkedin": "https://linkedin.com", "chatgpt": "https://chat.openai.com",
    "gmail": "https://gmail.com", "discord": "https://discord.com",
    "claude": "https://claude.ai",
}
APP_ENUM = sorted(set(APP_REGISTRY) | set(APP_URL_REGISTRY))
_SHELL_FOLDERS = {"this pc": "shell:MyComputerFolder"}

_LOCATION_ALIASES = {
    "desktop": "Desktop", "documents": "Documents", "my documents": "Documents",
    "downloads": "Downloads", "home": "",
}
_SYSTEM_ACTIONS = ("shutdown", "restart", "sleep", "lock", "hibernate")
_SAFE_READ = {".txt", ".py", ".js", ".html", ".css", ".json", ".md", ".log",
              ".ini", ".cfg", ".xml", ".csv", ".yaml"}


def _friendly(e: Exception) -> str:
    phrase, _ = classify_exception(e)
    return f"I wasn't able to complete that, Sir — {phrase or 'an unexpected error occurred'}."


def _launch_no_shell(executable: str, extra_args: list | None = None) -> None:
    args = [executable] + (extra_args or [])
    subprocess.Popen(args, shell=False)


def tool_open_app(target):
    target = str(target or "").lower().strip()
    if target not in APP_REGISTRY and target not in APP_URL_REGISTRY:
        return f"app_not_allowed: {target}"

    if target in APP_URL_REGISTRY:
        url = APP_URL_REGISTRY[target]
        safe, matched = safety_check(url)
        if not safe:
            return f"Blocked: '{matched}'"
        os.startfile(url)  # noqa: S606 — allowlisted URL
        add_alert(f"Opened: {target}")
        return f"Opened {target}, Sir."

    if target in _SHELL_FOLDERS:
        _launch_no_shell("explorer.exe", [_SHELL_FOLDERS[target]])
        add_alert(f"Opened: {target}")
        return f"Opened {target}, Sir."

    mapped = APP_REGISTRY[target]
    safe, matched = safety_check(mapped)
    if not safe:
        return f"Blocked: '{matched}'"
    if mapped.startswith("ms-settings:"):
        os.startfile(mapped)
    elif mapped.startswith("shell:"):
        _launch_no_shell("explorer.exe", [mapped])
    else:
        _launch_no_shell(mapped)
    add_alert(f"Opened: {target}")
    return f"Opened {target}, Sir."


def tool_open_url(url):
    url = str(url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "Blocked: URL must be http or https"
    if parsed.username or parsed.password:
        return "Blocked: credentials in URL are not allowed"
    safe, matched = safety_check(url)
    if not safe:
        return f"Blocked: '{matched}'"
    os.startfile(url)
    add_alert(f"Opened URL: {parsed.netloc}")
    return f"Opened {parsed.netloc}, Sir."


def tool_file_find(filename, search_path=None):
    root = Path(search_path) if search_path else HOME
    found = []
    try:
        for f in root.rglob("*"):
            if filename.lower() in f.name.lower():
                found.append(str(f))
            if len(found) >= 10:
                break
        return ("Found:\n" + "\n".join(found)) if found else f"No files matching '{filename}', Sir."
    except Exception as e:
        return _friendly(e)


def tool_file_read(filepath):
    p = Path(filepath)
    if not p.exists():
        return f"Not found: {filepath}"
    if p.suffix.lower() not in _SAFE_READ:
        return f"Cannot read binary file: {p.suffix}"
    if p.stat().st_size > 50000:
        return "File too large (>50KB), Sir."
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:3000]
    except Exception as e:
        return _friendly(e)


def tool_get_processes(filter_name=None):
    try:
        procs = [
            {"pid": p.info["pid"], "name": p.info["name"],
             "ram": round(p.info["memory_percent"] or 0, 1),
             "cpu": round(p.info["cpu_percent"] or 0, 1)}
            for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"])
            if not filter_name or filter_name.lower() in (p.info.get("name") or "").lower()
        ]
        procs.sort(key=lambda x: x["ram"], reverse=True)
        return "Processes:\n" + "\n".join(
            f"PID:{p['pid']} {p['name']:<25} RAM:{p['ram']}% CPU:{p['cpu']}%"
            for p in procs[:20]
        )
    except Exception as e:
        return _friendly(e)


def tool_kill_process(name_or_pid):
    name_or_pid = name_or_pid or ""
    try:
        try:
            pid = int(name_or_pid)
            p = psutil.Process(pid)
            p.terminate()
            add_alert(f"Killed PID {pid}")
            return f"PID {pid} terminated, Sir."
        except ValueError:
            pass
        killed = []
        for p in psutil.process_iter(["name", "pid"]):
            try:
                if name_or_pid.lower() in (p.info["name"] or "").lower():
                    p.terminate()
                    killed.append(p.info["pid"])
            except Exception:
                pass
        if killed:
            add_alert(f"Killed: {name_or_pid}")
            return f"Terminated {len(killed)} process(es), Sir."
        return f"No process found: '{name_or_pid}', Sir."
    except Exception as e:
        return _friendly(e)


def tool_get_system_status(_args=None):
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        vm = psutil.virtual_memory()
        bat = psutil.sensors_battery()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        up = int(time.time() - _server_start)
        return (
            f"CPU:{cpu}% | RAM:{vm.percent}% ({round(vm.used/1024**3,1)}GB/{round(vm.total/1024**3,1)}GB) | "
            f"Battery:{round(bat.percent) if bat else 'N/A'}%{'⚡' if bat and bat.power_plugged else ''} | "
            f"Disk:{disk.percent}% ({round(disk.free/1024**3,1)}GB free) | "
            f"Net:↓{round(net.bytes_recv/1024**2,1)}MB↑{round(net.bytes_sent/1024**2,1)}MB | "
            f"Uptime:{up//3600}h{(up%3600)//60}m"
        )
    except Exception as e:
        return _friendly(e)


def tool_take_screenshot(_args=None):
    if not PYAUTOGUI_OK:
        return "Screenshot unavailable (no display)."
    try:
        fname = f"screenshot_{int(time.time())}.png"
        ss = DATA_DIR / fname
        pyautogui.screenshot(str(ss))
        add_alert(f"Screenshot: {fname}")
        return f"Screenshot saved: {ss}, Sir."
    except Exception as e:
        return _friendly(e)


def tool_describe_screen(_args=None):
    if not PYAUTOGUI_OK:
        return "Screen capture unavailable (no display), Sir."
    try:
        ss_path = DATA_DIR / f"peek_{int(time.time())}.jpg"
        pyautogui.screenshot(str(ss_path))
        with open(ss_path, "rb") as f:
            img_b64 = __import__("base64").b64encode(f.read()).decode()
        prompt = ("Describe exactly what is visible on this screen in 2-3 sentences. "
                  "Be specific: what application, what content, any errors.")
        result = call_gemini(prompt, image_base64=img_b64)
        if result["ok"]:
            return groq_as_manager(
                "screen_describe", result["text"], max_tokens=120,
                context="Gemini analyzed the screen. Relay as JARVIS.",
            )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} "
             "| Select-Object Name,MainWindowTitle | Format-List"],
            shell=False, capture_output=True, text=True, timeout=5,
        )
        return (f"Active windows:\n{r.stdout.strip()[:600]}"
                if r.stdout.strip() else "Screen analysis unavailable, Sir.")
    except Exception as e:
        return _friendly(e)


def tool_take_snapshot(args=None):
    from config import EXECUTION_MODE, CV2_OK
    if EXECUTION_MODE != "local" or not CV2_OK:
        return {"ok": False, "error": "camera_unavailable"}
    args = args or {}
    width = args.get("width", 640)
    quality = args.get("quality", 0.7)
    if not isinstance(width, int) or width < 160 or width > 1920:
        return {"ok": False, "error": "invalid_arguments"}
    if not isinstance(quality, (int, float)) or not math.isfinite(quality) or quality < 0.1 or quality > 0.95:
        return {"ok": False, "error": "invalid_arguments"}
    import cv2

    capture = cv2.VideoCapture(0)
    try:
        if not capture.isOpened():
            return {"ok": False, "error": "camera_unavailable"}
        success, frame = capture.read()
        if not success:
            return {"ok": False, "error": "camera_unavailable"}
        height, frame_width = frame.shape[:2]
        if frame_width > width:
            ratio = width / frame_width
            frame = cv2.resize(frame, (width, max(1, round(height * ratio))))
        success, encoded = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, round(quality * 100)]
        )
        if not success:
            return {"ok": False, "error": "camera_capture_failed"}
        return {"image_b64": base64.b64encode(encoded.tobytes()).decode("ascii"), "mime": "image/jpeg"}
    finally:
        capture.release()


def tool_control_volume(action, level=None):
    if not PYAUTOGUI_OK:
        return "Volume control unavailable (no display)."
    try:
        a = str(action or "").lower()
        if a == "mute":
            pyautogui.press("volumemute")
            return "Muted, Sir."
        if a == "unmute":
            pyautogui.press("volumemute")
            return "Unmuted, Sir."
        if a in ("up", "louder"):
            pyautogui.press(["volumeup"] * 8)
            return "Volume increased, Sir."
        if a in ("down", "quieter"):
            pyautogui.press(["volumedown"] * 8)
            return "Volume decreased, Sir."
        if a == "max":
            pyautogui.press(["volumeup"] * 50)
            return "Volume at maximum, Sir."
        if a == "set" and level is not None:
            pyautogui.press(["volumedown"] * 50)
            if int(level) > 0:
                pyautogui.press(["volumeup"] * (int(level) // 2))
            return f"Volume set to {level}%, Sir."
        return f"Unknown volume action: {a}"
    except Exception as e:
        return _friendly(e)


def tool_type_text(text):
    if not PYAUTOGUI_OK:
        return "Type-text unavailable (no display)."
    try:
        time.sleep(0.3)
        pyautogui.typewrite(str(text or ""), interval=0.04)
        return "Typed, Sir."
    except Exception as e:
        return _friendly(e)


def tool_get_clipboard(_args=None):
    if not CLIP_OK:
        return "pyperclip not installed."
    try:
        t = pyperclip.paste()
        return f"Clipboard: {t[:500]}" if t else "Clipboard empty, Sir."
    except Exception as e:
        return _friendly(e)


def tool_set_clipboard(text):
    if not CLIP_OK:
        return "pyperclip not installed."
    try:
        pyperclip.copy(text or "")
        return "Clipboard set, Sir."
    except Exception as e:
        return _friendly(e)


def tool_create_folder(name, location=None):
    try:
        if location:
            key = str(location).strip().lower()
            if key in _LOCATION_ALIASES:
                sub = _LOCATION_ALIASES[key]
                base = (HOME / sub) if sub else HOME
            else:
                p = Path(location)
                base = p if p.is_absolute() else (HOME / p)
        else:
            base = HOME / "Desktop"
        if re.search(r"[<>:\"|?*]", name) or "/" in name or "\\" in name:
            return "Invalid folder name, Sir."
        fp = base / name
        fp.mkdir(parents=True, exist_ok=True)
        _launch_no_shell("explorer.exe", [str(fp)])
        add_alert(f"Folder: {fp}")
        return f"Folder '{name}' created at {fp}, Sir."
    except Exception as e:
        return _friendly(e)


def tool_system_action(action):
    if action not in _SYSTEM_ACTIONS:
        return f"Unknown system action: {action}"
    from command import perform_system_action
    return perform_system_action(action)


register(Tool(
    name="open_app",
    description="Open an allowlisted application or known website on this PC.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string", "enum": APP_ENUM}},
        "required": ["target"],
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_open_app(a.get("target", "")),
))
register(Tool(
    name="open_url",
    description="Open an http or https URL in the default browser.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_open_url(a.get("url", "")),
))
register(Tool(
    name="file_find",
    description="Find files by name on this PC.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "search_path": {"type": "string"},
        },
        "required": ["filename"],
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_file_find(a.get("filename", ""), a.get("search_path")),
))
register(Tool(
    name="file_read",
    description="Read a small text file on this PC.",
    parameters={
        "type": "object",
        "properties": {"filepath": {"type": "string"}},
        "required": ["filepath"],
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_file_read(a.get("filepath", "")),
))
register(Tool(
    name="get_processes",
    description="List running processes on this PC.",
    parameters={
        "type": "object",
        "properties": {"filter_name": {"type": "string"}},
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_get_processes(a.get("filter_name")),
))
register(Tool(
    name="kill_process",
    description="Terminate a process by name or PID. Requires confirmation.",
    parameters={
        "type": "object",
        "properties": {"name_or_pid": {"type": "string"}},
        "required": ["name_or_pid"],
    },
    where="device", risk="high",
    local_impl=lambda a: tool_kill_process(a.get("name_or_pid", "")),
))
register(Tool(
    name="get_system_status",
    description="CPU, RAM, battery, disk, and network stats for this PC.",
    parameters={"type": "object", "properties": {}},
    where="device", risk="low",
    local_impl=lambda a: tool_get_system_status(),
))
register(Tool(
    name="take_screenshot",
    description="Capture a screenshot and save it locally.",
    parameters={"type": "object", "properties": {}},
    where="device", risk="medium",
    local_impl=lambda a: tool_take_screenshot(),
))
register(Tool(
    name="describe_screen",
    description="Describe what is currently visible on this PC's screen.",
    parameters={"type": "object", "properties": {}},
    where="device", risk="medium",
    local_impl=lambda a: tool_describe_screen(),
))
register(Tool(
    name="take_snapshot",
    description="Take one on-demand camera snapshot and answer a question about the image.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "width": {"type": "integer", "minimum": 160, "maximum": 1920},
            "quality": {"type": "number", "minimum": 0.1, "maximum": 0.95},
        },
    },
    where="device", risk="medium",
    local_impl=tool_take_snapshot,
))
register(Tool(
    name="control_volume",
    description="Control system volume.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["mute", "unmute", "up", "down", "max", "set"]},
            "level": {"type": "integer"},
        },
        "required": ["action"],
    },
    where="device", risk="low",
    local_impl=lambda a: tool_control_volume(a.get("action", ""), a.get("level")),
))
register(Tool(
    name="type_text",
    description="Type text at the current cursor. Requires confirmation.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    where="device", risk="high",
    local_impl=lambda a: tool_type_text(a.get("text", "")),
))
register(Tool(
    name="get_clipboard",
    description="Read the clipboard on this PC.",
    parameters={"type": "object", "properties": {}},
    where="device", risk="medium",
    local_impl=lambda a: tool_get_clipboard(),
))
register(Tool(
    name="set_clipboard",
    description="Write text to the clipboard on this PC.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_set_clipboard(a.get("text", "")),
))
register(Tool(
    name="create_folder",
    description="Create a folder on this PC.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "location": {"type": "string"},
        },
        "required": ["name"],
    },
    where="device", risk="medium",
    local_impl=lambda a: tool_create_folder(a.get("name", ""), a.get("location")),
))
register(Tool(
    name="system_action",
    description=(
        "Shut down, restart, sleep, lock, or hibernate this PC. "
        "Requires confirmation. Only call when the user clearly asked."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_SYSTEM_ACTIONS)},
        },
        "required": ["action"],
    },
    where="device", risk="high",
    local_impl=lambda a: tool_system_action(a.get("action", "")),
))
