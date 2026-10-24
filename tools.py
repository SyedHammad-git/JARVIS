"""
J.A.R.V.I.S v17.M — Agent Tools
FIXED: C4 tool_describe_screen PYAUTOGUI_OK guard, H2 shell injection in run_shell_safe
"""
import base64, logging, re, subprocess, time
from pathlib import Path
import psutil

try:
    import pyautogui; PYAUTOGUI_OK = True
except Exception:
    pyautogui = None; PYAUTOGUI_OK = False
    print("[TOOLS] ⚠  pyautogui unavailable — GUI tools disabled")

from config import (
    REQUESTS_OK, _req, DDGS_OK, DDGS,
    CLIP_OK, pyperclip, WEATHER_KEY,
    _server_start
)
from database import HOME, DATA_DIR
from auth import safety_check, add_alert
from ai_engine import call_gemini, groq_as_manager
from command import perform_system_action  # TASK-023: shared with cmd_route's keyword path
from error_utils import classify_exception, CircuitBreaker
from memory import search_facts_semantic

log = logging.getLogger("jarvis.tools")

_weather_breaker = CircuitBreaker(threshold=3, cooldown=60)

def _friendly(e: Exception) -> str:
    """TASK-030: same JARVIS-toned phrasing as agent.py::execute_tool()'s
    wrapper and the route-level error handler (error_utils.py), so a
    tool's own error string reads the same regardless of which layer
    catches the exception — most tools here catch their own errors
    directly instead of letting them reach execute_tool(), so this is
    where the actual raw-exception text was reaching the model/user."""
    phrase, _ = classify_exception(e)
    return f"I wasn't able to complete that, Sir — {phrase or 'an unexpected error occurred'}."

def tool_web_search(query, max_results=5):
    if not DDGS_OK: return "Install: pip install duckduckgo-search"
    try:
        with DDGS() as d: results = list(d.text(query, max_results=max_results))
        return ("\n\n".join(
            f"• {r.get('title','')}\n  {r.get('body','')[:300]}"
            for r in results[:max_results]
        )) if results else "No results found, Sir."
    except Exception as e: return _friendly(e)

APP_REGISTRY = {
    "chrome":"chrome","google chrome":"chrome",
    "vscode":"code","code":"code","visual studio code":"code",
    "word":"winword","microsoft word":"winword",
    "excel":"excel","microsoft excel":"excel",
    "powerpoint":"powerpnt","outlook":"outlook",
    "spotify":"spotify","calculator":"calc","calc":"calc",
    "notepad":"notepad","task manager":"taskmgr",
    "file explorer":"explorer","explorer":"explorer",
    "this pc":"explorer.exe shell:MyComputerFolder",
    "documents":"explorer.exe shell:Personal","downloads":"explorer.exe shell:Downloads",
    "desktop":"explorer.exe shell:Desktop","paint":"mspaint",
    "cmd":"cmd","powershell":"powershell","edge":"msedge","firefox":"firefox",
    "teams":"teams","zoom":"zoom","settings":"ms-settings:",
}
# Web "apps" with no local executable — opened via the default browser.
APP_URL_REGISTRY = {
    "youtube":"https://youtube.com","google":"https://google.com",
    "whatsapp":"https://web.whatsapp.com","github":"https://github.com",
    "linkedin":"https://linkedin.com","chatgpt":"https://chat.openai.com",
    "gmail":"https://gmail.com","discord":"https://discord.com",
    "claude":"https://claude.ai",
}

def _exe_resolvable(name: str) -> bool:
    """Best-effort check for whether `name` can be resolved as a runnable
    command, via PowerShell's Get-Command (broader than `where` — also
    catches cmdlets/aliases). NOT exhaustive: GUI apps launched through
    Windows' App Paths registry or a Start Menu shortcut can still work via
    `start <name>` even when Get-Command can't see them, so a False here
    is treated as a signal, not absolute proof the launch will fail.
    Returns True (i.e. "don't block the attempt") if the check itself can't
    run at all, e.g. PowerShell unavailable — never let a broken diagnostic
    silently disable app-opening entirely."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"if (Get-Command '{name}' -ErrorAction SilentlyContinue) {{exit 0}} else {{exit 1}}"],
            timeout=5, capture_output=True
        )
        return r.returncode == 0
    except Exception:
        return True

def tool_open_app(target):
    t = target.lower().strip()
    if t in APP_URL_REGISTRY:
        cmd = APP_URL_REGISTRY[t]
    else:
        cmd = APP_REGISTRY.get(t, target)
        # Only verify plain executable-style targets — a shell: URI or a
        # multi-word "explorer.exe shell:X" command isn't something
        # Get-Command can meaningfully check.
        if " " not in cmd and ":" not in cmd and not _exe_resolvable(cmd):
            return (f"I couldn't find an application called '{target}' on this PC, Sir — "
                    f"it may not be installed, or isn't registered under that name.")

    safe, matched = safety_check(cmd)
    if not safe: return f"Blocked: '{matched}'"
    try:
        subprocess.Popen(f"start {cmd}", shell=True)
    except Exception as e:
        return _friendly(e)
    add_alert(f"Opened: {target}")
    return f"Opened {target}, Sir."

def tool_file_find(filename, search_path=None):
    root = Path(search_path) if search_path else HOME
    found = []
    try:
        for f in root.rglob("*"):
            if filename.lower() in f.name.lower(): found.append(str(f))
            if len(found) >= 10: break
        return ("Found:\n" + "\n".join(found)) if found else f"No files matching '{filename}', Sir."
    except Exception as e: return _friendly(e)

def tool_file_read(filepath):
    SAFE = {".txt",".py",".js",".html",".css",".json",".md",".log",".ini",".cfg",".xml",".csv",".yaml"}
    p = Path(filepath)
    if not p.exists(): return f"Not found: {filepath}"
    if p.suffix.lower() not in SAFE: return f"Cannot read binary file: {p.suffix}"
    if p.stat().st_size > 50000: return "File too large (>50KB), Sir."
    try: return p.read_text(encoding="utf-8", errors="replace")[:3000]
    except Exception as e: return _friendly(e)

def tool_get_processes(filter_name=None):
    try:
        procs = [
            {"pid": p.info["pid"], "name": p.info["name"],
             "ram": round(p.info["memory_percent"] or 0, 1),
             "cpu": round(p.info["cpu_percent"] or 0, 1)}
            for p in psutil.process_iter(["pid","name","memory_percent","cpu_percent"])
            if not filter_name or filter_name.lower() in (p.info.get("name") or "").lower()
        ]
        procs.sort(key=lambda x: x["ram"], reverse=True)
        return "Processes:\n" + "\n".join(
            f"PID:{p['pid']} {p['name']:<25} RAM:{p['ram']}% CPU:{p['cpu']}%"
            for p in procs[:20]
        )
    except Exception as e: return _friendly(e)

def tool_kill_process(name_or_pid):
    try:
        try:
            pid = int(name_or_pid)
            p = psutil.Process(pid); p.terminate()
            add_alert(f"Killed PID {pid}")
            return f"PID {pid} terminated, Sir."
        except ValueError: pass
        killed = []
        for p in psutil.process_iter(["name","pid"]):
            try:
                if name_or_pid.lower() in (p.info["name"] or "").lower():
                    p.terminate(); killed.append(p.info["pid"])
            except: pass
        if killed: add_alert(f"Killed: {name_or_pid}"); return f"Terminated {len(killed)} process(es), Sir."
        return f"No process found: '{name_or_pid}', Sir."
    except Exception as e: return _friendly(e)

def tool_get_system_status():
    try:
        cpu  = psutil.cpu_percent(interval=0.5)
        vm   = psutil.virtual_memory()
        bat  = psutil.sensors_battery()
        disk = psutil.disk_usage("/")
        net  = psutil.net_io_counters()
        up   = int(time.time() - _server_start)
        return (
            f"CPU:{cpu}% | RAM:{vm.percent}% ({round(vm.used/1024**3,1)}GB/{round(vm.total/1024**3,1)}GB) | "
            f"Battery:{round(bat.percent) if bat else 'N/A'}%{'⚡' if bat and bat.power_plugged else ''} | "
            f"Disk:{disk.percent}% ({round(disk.free/1024**3,1)}GB free) | "
            f"Net:↓{round(net.bytes_recv/1024**2,1)}MB↑{round(net.bytes_sent/1024**2,1)}MB | "
            f"Uptime:{up//3600}h{(up%3600)//60}m"
        )
    except Exception as e: return _friendly(e)

def tool_take_screenshot():
    if not PYAUTOGUI_OK: return "Screenshot unavailable (no display)."
    try:
        fname = f"screenshot_{int(time.time())}.png"
        ss    = DATA_DIR / fname
        pyautogui.screenshot(str(ss))
        add_alert(f"Screenshot: {fname}")
        return f"Screenshot saved: {ss}, Sir."
    except Exception as e: return _friendly(e)

def tool_describe_screen():
    # ✅ FIX C4: guard with PYAUTOGUI_OK before calling pyautogui.screenshot
    if not PYAUTOGUI_OK:
        return "Screen capture unavailable (no display), Sir."
    try:
        ss_path = DATA_DIR / f"peek_{int(time.time())}.jpg"
        pyautogui.screenshot(str(ss_path))
        with open(ss_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        prompt = ("Describe exactly what is visible on this screen in 2-3 sentences. "
                  "Be specific: what application, what content, any errors.")
        result = call_gemini(prompt, image_base64=img_b64)
        if result["ok"]:
            return groq_as_manager("screen_describe", result["text"], max_tokens=120,
                                   context="Gemini analyzed the screen. Relay as JARVIS.")
        r = subprocess.run(
            'powershell -Command "Get-Process | Where-Object {$_.MainWindowTitle -ne \'\'} '
            '| Select-Object Name,MainWindowTitle | Format-List"',
            shell=True, capture_output=True, text=True, timeout=5
        )
        return (f"Active windows:\n{r.stdout.strip()[:600]}"
                if r.stdout.strip() else "Screen analysis unavailable, Sir.")
    except Exception as e: return _friendly(e)

def tool_control_volume(action, level=None):
    if not PYAUTOGUI_OK: return "Volume control unavailable (no display)."
    try:
        a = action.lower()
        if a == "mute":    pyautogui.press("volumemute"); return "Muted, Sir."
        if a == "unmute":  pyautogui.press("volumemute"); return "Unmuted, Sir."
        if a in ("up","louder"):    pyautogui.press(["volumeup"]*8);   return "Volume increased, Sir."
        if a in ("down","quieter"): pyautogui.press(["volumedown"]*8); return "Volume decreased, Sir."
        if a == "max":     pyautogui.press(["volumeup"]*50); return "Volume at maximum, Sir."
        if a == "set" and level is not None:
            pyautogui.press(["volumedown"]*50)
            if level > 0: pyautogui.press(["volumeup"]*(level//2))
            return f"Volume set to {level}%, Sir."
        return f"Unknown volume action: {action}"
    except Exception as e: return _friendly(e)

def tool_type_text(text):
    if not PYAUTOGUI_OK: return "Type-text unavailable (no display)."
    try: time.sleep(0.3); pyautogui.typewrite(str(text), interval=0.04); return "Typed, Sir."
    except Exception as e: return _friendly(e)

# ✅ FIX H2: Block shell chaining operators in run_shell_safe
_SAFE_PREFIXES = [
    "start ","explorer","calc","notepad","mspaint","tasklist","ipconfig",
    "ping ","whoami","hostname","dir ","echo ","systeminfo","netstat",
    "wmic","msinfo32","winver","vol","ver ","time /t","date /t",
]
_BLOCK_PATTERNS = re.compile(r"[&|;><`$]|\bsudo\b|\brm\b|\bdel\b|\brmdir\b", re.IGNORECASE)

def tool_run_shell_safe(command):
    safe, matched = safety_check(command)
    if not safe: return f"BLOCKED: '{matched}'"
    # ✅ FIX H2: Reject any chaining operators regardless of prefix
    if _BLOCK_PATTERNS.search(command):
        return "BLOCKED: dangerous operator in command"
    if not any(command.lower().startswith(p) for p in _SAFE_PREFIXES):
        if not re.match(r'^(cd|mkdir|copy|move|ren)\s+', command.lower()):
            return f"Not in safe command list: {command}"
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=12)
        add_alert(f"Shell: {command[:40]}")
        return (r.stdout or r.stderr or "Done.").strip()[:1200]
    except subprocess.TimeoutExpired: return "Command timed out."
    except Exception as e: return _friendly(e)

def tool_get_weather(city="Faisalabad"):
    if not REQUESTS_OK: return "requests not installed."
    if not _weather_breaker.available():
        return "The weather service is temporarily unavailable, Sir — I'll try again shortly."

    owm_key_invalid = False
    if WEATHER_KEY:
        try:
            r = _req.get("https://api.openweathermap.org/data/2.5/weather",
                         params={"q":city,"appid":WEATHER_KEY,"units":"metric"}, timeout=10)
            if r.status_code == 200:
                d = r.json()
                temp=round(d["main"]["temp"]); feels=round(d["main"]["feels_like"])
                desc=d["weather"][0]["description"].capitalize()
                hum=d["main"]["humidity"]; wind=round(d["wind"]["speed"]*3.6)
                _weather_breaker.record_success()
                return (f"Weather in {city}: {temp}°C (feels {feels}°C) — {desc} | "
                        f"Humidity: {hum}% | Wind: {wind} km/h")
            # Non-200: log exactly what OWM said — status code AND body —
            # so a bad key / unknown city / rate-limit shows up in
            # ~/JARVIS_Data/jarvis.log instead of silently falling through
            # to wttr.in with no trace of why.
            log.warning("OWM weather failed for %r: HTTP %s — %s",
                        city, r.status_code, r.text[:300])
            if r.status_code in (401, 403):
                owm_key_invalid = True
        except Exception as e:
            log.warning("OWM request error for %r: %s — falling back to wttr.in", city, e)
    else:
        log.info("WEATHER_KEY not set — skipping OWM, using wttr.in directly")

    try:
        r = _req.get(f"https://wttr.in/{city}?format=j1", timeout=10,
                     headers={"User-Agent":"JARVIS/17.0"})
        if r.status_code == 200:
            cur = r.json()["current_condition"][0]
            _weather_breaker.record_success()
            return (f"Weather in {city}: {cur['temp_C']}°C (feels {cur['FeelsLikeC']}°C) "
                    f"— {cur['weatherDesc'][0]['value']} | "
                    f"Humidity: {cur['humidity']}% | Wind: {cur['windspeedKmph']} km/h")
        log.warning("wttr.in failed for %r: HTTP %s — %s", city, r.status_code, r.text[:300])
    except Exception as e:
        log.warning("wttr.in request error for %r: %s", city, e)
        _weather_breaker.record_failure()
        if owm_key_invalid:
            return ("Weather API Key is missing or invalid in .env file, Sir — "
                    "and the backup weather service is unreachable right now too.")
        return _friendly(e)

    _weather_breaker.record_failure()
    if owm_key_invalid:
        return ("Weather API Key is missing or invalid in .env file, Sir — "
                "the backup weather service didn't have data for that city either.")
    return "Weather unavailable, Sir."

def tool_get_clipboard():
    if not CLIP_OK: return "pyperclip not installed."
    try:
        t = pyperclip.paste()
        return f"Clipboard: {t[:500]}" if t else "Clipboard empty, Sir."
    except Exception as e: return _friendly(e)

def tool_set_clipboard(text):
    if not CLIP_OK: return "pyperclip not installed."
    try: pyperclip.copy(text); return "Clipboard set, Sir."
    except Exception as e: return _friendly(e)

_LOCATION_ALIASES = {"desktop":"Desktop", "documents":"Documents", "my documents":"Documents",
                     "downloads":"Downloads", "home":""}

def tool_create_folder(name, location=None):
    try:
        if location:
            key = location.strip().lower()
            if key in _LOCATION_ALIASES:
                sub  = _LOCATION_ALIASES[key]
                base = (HOME / sub) if sub else HOME
            else:
                p = Path(location)
                # A bare/relative-looking location (no drive letter, no
                # leading slash) is almost certainly meant relative to the
                # user's home, not wherever the Flask process's current
                # working directory happens to be — resolving it under CWD
                # is exactly what was silently dropping folders into the
                # project directory instead of the real Desktop/Documents.
                base = p if p.is_absolute() else (HOME / p)
        else:
            base = HOME / "Desktop"
        fp = base / name   # pathlib handles spaces in `name` natively, no escaping needed
        fp.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(f'explorer "{fp}"', shell=True)
        add_alert(f"Folder: {fp}")
        return f"Folder '{name}' created at {fp}, Sir."
    except Exception as e: return _friendly(e)

# TASK-023: agent-callable version of the 5 safety-critical actions in
# command.py. The model can only pick from the fixed enum below (see
# AGENT_TOOLS) — it never supplies a raw command string, so however the
# request was phrased (English, Urdu, Roman Urdu, casual), execution still
# goes through perform_system_action()'s exact same reviewed subprocess
# calls that cmd_route's keyword match uses.
def tool_system_action(action):
    if action not in ("shutdown", "restart", "sleep", "lock", "hibernate"):
        return f"Unknown system action: {action}"
    return perform_system_action(action)

def tool_search_memory(query, top_k=5):
    hits = search_facts_semantic(query, top_k=int(top_k) if top_k else 5)
    if not hits:
        return "No stored facts matched that, Sir."
    return "\n".join(f"• {h['fact']} ({h['category']})" for h in hits)

AGENT_TOOLS = [
    {"type":"function","function":{"name":"web_search","description":"Search internet","parameters":{"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer"}},"required":["query"]}}},
    {"type":"function","function":{"name":"open_app","description":"Open app/website/folder","parameters":{"type":"object","properties":{"target":{"type":"string"}},"required":["target"]}}},
    {"type":"function","function":{"name":"file_find","description":"Find files by name","parameters":{"type":"object","properties":{"filename":{"type":"string"},"search_path":{"type":"string"}},"required":["filename"]}}},
    {"type":"function","function":{"name":"file_read","description":"Read text file","parameters":{"type":"object","properties":{"filepath":{"type":"string"}},"required":["filepath"]}}},
    {"type":"function","function":{"name":"get_processes","description":"List processes","parameters":{"type":"object","properties":{"filter_name":{"type":"string"}}}}},
    {"type":"function","function":{"name":"kill_process","description":"Kill process by name or PID","parameters":{"type":"object","properties":{"name_or_pid":{"type":"string"}},"required":["name_or_pid"]}}},
    {"type":"function","function":{"name":"get_system_status","description":"CPU/RAM/battery/disk/network","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"take_screenshot","description":"Take screenshot","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"describe_screen","description":"Describe current screen via Gemini Vision","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"control_volume","description":"Volume control","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["mute","unmute","up","down","max","set"]},"level":{"type":"integer"}},"required":["action"]}}},
    {"type":"function","function":{"name":"type_text","description":"Type text at cursor","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"run_shell_safe","description":"Run safe Windows shell command","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}},
    {"type":"function","function":{"name":"get_weather","description":"Get weather for city","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}},
    {"type":"function","function":{"name":"get_clipboard","description":"Read clipboard","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"set_clipboard","description":"Write to clipboard","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"create_folder","description":"Create folder","parameters":{"type":"object","properties":{"name":{"type":"string"},"location":{"type":"string"}},"required":["name"]}}},
    {"type":"function","function":{"name":"system_action","description":"Shut down, restart, sleep, lock, or hibernate the PC. Executes immediately and irreversibly — only call this when the user has clearly asked for one of these five actions, in any language or phrasing.","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["shutdown","restart","sleep","lock","hibernate"]}},"required":["action"]}}},
    {"type":"function","function":{"name":"search_memory","description":"Search facts JARVIS has previously been asked to remember, by meaning rather than exact wording — use this when the user references something from an earlier conversation.","parameters":{"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer"}},"required":["query"]}}},
]

TOOL_REG = {
    "web_search":        lambda a: tool_web_search(a.get("query",""), a.get("max_results",5)),
    "open_app":          lambda a: tool_open_app(a.get("target","")),
    "file_find":         lambda a: tool_file_find(a.get("filename",""), a.get("search_path")),
    "file_read":         lambda a: tool_file_read(a.get("filepath","")),
    "get_processes":     lambda a: tool_get_processes(a.get("filter_name")),
    "kill_process":      lambda a: tool_kill_process(a.get("name_or_pid","")),
    "get_system_status": lambda a: tool_get_system_status(),
    "take_screenshot":   lambda a: tool_take_screenshot(),
    "describe_screen":   lambda a: tool_describe_screen(),
    "control_volume":    lambda a: tool_control_volume(a.get("action",""), a.get("level")),
    "type_text":         lambda a: tool_type_text(a.get("text","")),
    "run_shell_safe":    lambda a: tool_run_shell_safe(a.get("command","")),
    "get_weather":       lambda a: tool_get_weather(a.get("city","Faisalabad")),
    "get_clipboard":     lambda a: tool_get_clipboard(),
    "set_clipboard":     lambda a: tool_set_clipboard(a.get("text","")),
    "create_folder":     lambda a: tool_create_folder(a.get("name",""), a.get("location")),
    "system_action":     lambda a: tool_system_action(a.get("action","")),
    "search_memory":     lambda a: tool_search_memory(a.get("query",""), a.get("top_k",5)),
}
