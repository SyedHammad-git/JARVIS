"""
╔══════════════════════════════════════════════════════════════════╗
║  J.A.R.V.I.S v17.M — Monitor & Camera Engine                   ║
║  FIXED:                                                          ║
║    BUG-1  CPU/RAM alert cooldown (was spamming every 2s)        ║
║    BUG-5  disk_usage "/" → platform-aware path                  ║
║    BUG-C  monitors table uses config JSON column correctly       ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import logging
import platform
import subprocess
import threading
import time
from threading import Lock

import psutil

from config import CV2_OK, EXECUTION_MODE, REQUESTS_OK, _req, cache, stat_lock
from database import db_read, db_write, db_write_many, ts, DATA_DIR
from auth import add_alert
from notifications import send_discord_alert

log = logging.getLogger("jarvis.monitor")

LOCAL_CAMERA_ENABLED = CV2_OK and EXECUTION_MODE == "local"

if LOCAL_CAMERA_ENABLED:
    import cv2

# ── Module-level state ────────────────────────────────────────────
cam_lock               = Lock()
monitor_engine_running = False
cameras                = {}
cam_id_counter         = [0]

motion_cfg = {
    "enabled": False, "threshold": 2500, "cooldown": 30, "last_alert": 0
}

# ✅ BUG-1 FIX: Alert cooldown tracker — prevents same alert firing every 2s
# Key = alert type (str), Value = last fired epoch (float)
_alert_cooldowns: dict = {}
_ALERT_COOLDOWN_SECS   = 300   # one alert per type every 5 minutes max
MONITOR_CACHE_TTL_SECONDS = 30 * 60
MONITOR_DB_HEARTBEAT_SECONDS = 15 * 60
_monitor_cache_lock = Lock()
_monitor_cache: list[dict] | None = None
_monitor_cache_synced_at = 0.0
_monitor_db_state: dict[int, dict] = {}


def refresh_monitor_cache(force: bool = False, now: float | None = None) -> list[dict]:
    global _monitor_cache, _monitor_cache_synced_at, _monitor_db_state
    instant = time.monotonic() if now is None else now
    with _monitor_cache_lock:
        if (_monitor_cache is not None and not force
                and instant - _monitor_cache_synced_at < MONITOR_CACHE_TTL_SECONDS):
            return [dict(monitor) for monitor in _monitor_cache]
        monitors = db_read("SELECT * FROM monitors ORDER BY id ASC")
        _monitor_cache = [dict(monitor) for monitor in monitors]
        _monitor_cache_synced_at = instant
        _monitor_db_state = {
            monitor["id"]: {
                "persisted_status": monitor.get("status", ""),
                "last_write": instant,
                "pending_trigger_count": 0,
            }
            for monitor in _monitor_cache if monitor.get("id") is not None
        }
        return [dict(monitor) for monitor in _monitor_cache]


def invalidate_monitor_cache() -> None:
    global _monitor_cache, _monitor_cache_synced_at
    with _monitor_cache_lock:
        _monitor_cache = None
        _monitor_cache_synced_at = 0.0


def get_monitor_cache() -> list[dict]:
    return refresh_monitor_cache()


def _record_monitor_check(
    monitor: dict,
    status: str,
    last_check: str,
    result: str,
    alert_sent: int,
    increment_trigger_count: bool,
    write_history: bool = True,
) -> None:
    monitor_id = monitor.get("id")
    if monitor_id is None:
        return
    with _monitor_cache_lock:
        cached = next((item for item in (_monitor_cache or []) if item.get("id") == monitor_id), None)
        if cached is None:
            if _monitor_cache is None:
                return
            cached = dict(monitor)
            _monitor_cache.append(cached)
        state = _monitor_db_state.setdefault(monitor_id, {
            "persisted_status": monitor.get("status", ""),
            "last_write": time.monotonic(),
            "pending_trigger_count": 0,
        })
        cached["status"] = status
        cached["last_check"] = last_check
        if increment_trigger_count:
            cached["trigger_count"] = int(cached.get("trigger_count") or 0) + 1
            state["pending_trigger_count"] += 1

        now = time.monotonic()
        state_changed = status != state["persisted_status"]
        heartbeat_due = now - state["last_write"] >= MONITOR_DB_HEARTBEAT_SECONDS
        if not state_changed and not heartbeat_due:
            return

        if increment_trigger_count:
            update = (
                "UPDATE monitors SET status=?,last_check=?,trigger_count=trigger_count+? WHERE id=?",
                (status, last_check, state["pending_trigger_count"], monitor_id),
            )
        else:
            update = (
                "UPDATE monitors SET status=?,last_check=? WHERE id=?",
                (status, last_check, monitor_id),
            )
        writes = [update]
        if write_history:
            writes.append((
                "INSERT INTO monitor_log(monitor_id,monitor_name,result,alert_sent,created_at)"
                " VALUES(?,?,?,?,?)",
                (monitor_id, cached.get("name", ""), result, alert_sent, last_check),
            ))
        writes_ok = db_write_many(writes)
        if writes_ok:
            state["persisted_status"] = status
            state["last_write"] = now
            state["pending_trigger_count"] = 0


def _should_alert(key: str, cooldown: int = _ALERT_COOLDOWN_SECS) -> bool:
    """Return True only if cooldown has passed since last alert of this type."""
    now = time.time()
    if now - _alert_cooldowns.get(key, 0) >= cooldown:
        _alert_cooldowns[key] = now
        return True
    return False


def _make_cams():
    try:
        rows = db_read("SELECT * FROM cameras ORDER BY id ASC")
        for row in rows:
            cid = row.get("id")
            cameras[cid] = {
                "name":   row.get("name", f"Camera {cid}"),
                "source": row.get("source", "0"),
                "active": bool(row.get("active", 0)),
                "cap":    None,
            }
            if cid > cam_id_counter[0]:
                cam_id_counter[0] = cid
    except Exception as e:
        log.warning("Camera DB load: %s", e)


_make_cams()

# ── Window tracker ────────────────────────────────────────────────
def get_active_window() -> str:
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle -ne ''}"
             " | Sort-Object CPU -Descending"
             " | Select-Object -First 1 -ExpandProperty MainWindowTitle"],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def window_tracker_loop():
    while True:
        try:
            win = get_active_window()
            with stat_lock:
                cache["active_window"] = win
                cache["active_app"]    = win.split(" - ")[-1] if " - " in win else win
        except Exception:
            pass
        time.sleep(10)   # reduced from 5s — less PowerShell overhead


# ── System stats background thread ───────────────────────────────
def monitor():
    global _pn
    _pn = psutil.net_io_counters()

    # ✅ BUG-5 FIX: platform-aware disk path
    _disk_path = "C:\\" if platform.system() == "Windows" else "/"

    while True:
        try:
            cpu  = psutil.cpu_percent(interval=1)
            vm   = psutil.virtual_memory()
            bat  = psutil.sensors_battery()
            disk = psutil.disk_usage(_disk_path)
            curr = psutil.net_io_counters()

            procs = sorted(
                [
                    {
                        "pid":  p.info["pid"],
                        "name": p.info["name"],
                        "cpu":  round(p.info["cpu_percent"] or 0, 1),
                        "ram":  round(p.info["memory_percent"] or 0, 1),
                    }
                    for p in psutil.process_iter(
                        ["pid", "name", "cpu_percent", "memory_percent"]
                    )
                ],
                key=lambda x: x["ram"],
                reverse=True,
            )[:15]

            with stat_lock:
                cache["cpu"]        = cpu
                cache["ram"]        = vm.percent
                cache["ram_used"]   = round(vm.used  / 1024 ** 3, 1)
                cache["ram_total"]  = round(vm.total / 1024 ** 3, 1)
                cache["battery"]    = round(bat.percent) if bat else 0
                cache["charging"]   = bat.power_plugged  if bat else False
                cache["net_down"]   = round((curr.bytes_recv - _pn.bytes_recv) / 1024, 1)
                cache["net_up"]     = round((curr.bytes_sent - _pn.bytes_sent) / 1024, 1)
                cache["disk_pct"]   = disk.percent
                cache["disk_used"]  = round(disk.used  / 1024 ** 3, 1)
                cache["disk_total"] = round(disk.total / 1024 ** 3, 1)
                cache["processes"]  = procs
                _pn = curr

            # ✅ BUG-1 FIX: cooldown guard — alert fires MAX once per 5 minutes per type
            if cpu > 90 and _should_alert("cpu_spike"):
                add_alert(f"⚠ CPU spike: {round(cpu)}%")

            if vm.percent > 92 and _should_alert("ram_critical"):
                add_alert(f"⚠ RAM critical: {round(vm.percent)}%")

        except Exception as e:
            log.error("monitor loop: %s", e)

        time.sleep(2)


# ── Camera helpers ────────────────────────────────────────────────
def _open_cap(cam: dict):
    if not LOCAL_CAMERA_ENABLED:
        return None
    src = cam.get("source", 0)
    try:
        if isinstance(src, str) and (src.startswith("http") or src.startswith("rtsp")):
            cap = cv2.VideoCapture(src)
        else:
            cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap if cap.isOpened() else None
    except Exception:
        return None


def _gen_frames(cam_id: int):
    if not LOCAL_CAMERA_ENABLED:
        yield b""
        return

    with cam_lock:
        cam = cameras.get(cam_id)
        if not cam:
            return
        if cam["cap"] is None:
            cam["cap"] = _open_cap(cam)
        cap = cam["cap"]

    if cap is None or not cap.isOpened():
        return

    prev_gray = None

    while True:
        with cam_lock:
            cam = cameras.get(cam_id)
            if not cam or not cam.get("active"):
                break
            success, frame = cap.read()

        if not success:
            time.sleep(0.05)
            continue

        try:
            if motion_cfg["enabled"]:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                if prev_gray is not None:
                    diff   = cv2.absdiff(prev_gray, gray)
                    thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
                    px     = cv2.countNonZero(thresh)
                    now    = time.time()
                    if (
                        px > motion_cfg["threshold"]
                        and now - motion_cfg["last_alert"] > motion_cfg["cooldown"]
                    ):
                        motion_cfg["last_alert"] = now
                        snap = str(DATA_DIR / f"motion_{int(now)}.jpg")
                        cv2.imwrite(snap, frame)
                        msg = f"Motion detected: {cameras[cam_id]['name']}"
                        add_alert(f"🚨 {msg}")
                        threading.Thread(
                            target=send_discord_alert, args=(msg, snap), daemon=True
                        ).start()
                prev_gray = gray
        except Exception:
            pass

        try:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + buf.tobytes()
                + b"\r\n"
            )
        except Exception:
            pass

        time.sleep(0.033)


# ── Monitor engine ────────────────────────────────────────────────
def check_monitor(mon: dict):
    """
    Run one uptime check for a monitor entry.
    URL/timeout stored in config JSON column — parsed here.
    """
    mon_id = mon.get("id")
    name   = mon.get("name", "")
    typ    = mon.get("type", "http")

    try:
        cfg = json.loads(mon.get("config", "{}") or "{}")
    except (json.JSONDecodeError, TypeError):
        cfg = {}

    url     = cfg.get("url", "")
    timeout = int(cfg.get("timeout", 10))

    if not url:
        log.warning("Monitor %s ('%s') has no URL in config — skipping", mon_id, name)
        return

    try:
        start = time.time()

        if typ in ("http", "https"):
            if not REQUESTS_OK:
                return
            r       = _req.get(
                url, timeout=timeout, allow_redirects=True,
                headers={"User-Agent": "JARVIS-Monitor/17.0"},
            )
            elapsed = round((time.time() - start) * 1000)
            status  = "up" if r.status_code < 500 else "down"
            result_str = f"HTTP {r.status_code} in {elapsed}ms"

            now = ts()
            _record_monitor_check(
                mon, status, now, result_str, 0 if status == "up" else 1,
                increment_trigger_count=True,
            )

            if status == "down":
                add_alert(f"🔴 Monitor DOWN: {name} (HTTP {r.status_code})")
                threading.Thread(
                    target=send_discord_alert,
                    args=(f"🔴 JARVIS Monitor: **{name}** is DOWN",),
                    daemon=True,
                ).start()

        elif typ == "ping":
            param = "-n" if platform.system() == "Windows" else "-c"
            host  = url.replace("http://", "").replace("https://", "").split("/")[0]
            r2    = subprocess.run(
                ["ping", param, "1", host],
                capture_output=True, text=True, timeout=10,
            )
            elapsed    = round((time.time() - start) * 1000)
            status     = "up" if r2.returncode == 0 else "down"
            result_str = f"Ping {'OK' if status == 'up' else 'FAIL'} in {elapsed}ms"

            now = ts()
            _record_monitor_check(
                mon, status, now, result_str, 0 if status == "up" else 1,
                increment_trigger_count=False,
            )

            if status == "down":
                add_alert(f"🔴 Ping DOWN: {name}")

    except Exception as e:
        _record_monitor_check(
            mon, "error", ts(), type(e).__name__, 0,
            increment_trigger_count=False,
            write_history=False,
        )
        log.error("Monitor check '%s': %s", name, e)


def monitor_engine_tick():
    mons = [
        monitor for monitor in refresh_monitor_cache()
        if monitor.get("active", 1) and monitor.get("status") != "paused"
    ]
    for monitor in mons:
        threading.Thread(target=check_monitor, args=(monitor,), daemon=True).start()


def run_monitor_engine():
    global monitor_engine_running
    monitor_engine_running = True
    log.info("Monitor engine started")
    refresh_monitor_cache()

    while True:
        try:
            monitor_engine_tick()
        except Exception as e:
            log.error("Monitor engine: %s", e)
        time.sleep(60)


def start_background_threads():
    threading.Thread(target=window_tracker_loop, daemon=True, name="WindowTracker").start()
    threading.Thread(target=monitor,             daemon=True, name="SysMonitor").start()
    threading.Thread(target=run_monitor_engine,  daemon=True, name="MonitorEngine").start()
    print("[MONITOR] ✅ Background threads started (WindowTracker, SysMonitor, MonitorEngine)")
