"""
J.A.R.V.I.S v17.M — Smart Home Module
FIXED: L4 removed duplicate TUYA_OK (now imported from config)
"""
import json
from app.db import cfg_get, cfg_set
from app.auth import add_alert

def _load_devices() -> dict:
    raw = cfg_get("smarthome_devices","")
    if raw:
        try: return json.loads(raw)
        except Exception: pass
    return {
        "light_1": {"name":"Main Light",   "state":False,"type":"light","icon":"💡","room":"Living Room"},
        "light_2": {"name":"Bedroom Light","state":False,"type":"light","icon":"💡","room":"Bedroom"},
        "fan_1":   {"name":"Ceiling Fan",  "state":False,"type":"fan",  "icon":"🌀","room":"Living Room"},
        "ac_1":    {"name":"AC Unit",      "state":False,"type":"ac",   "icon":"❄️","room":"Bedroom"},
        "plug_1":  {"name":"Smart Plug",   "state":False,"type":"plug", "icon":"🔌","room":"Office"},
    }

smarthome_devices = _load_devices()

def save_devices():
    cfg_set("smarthome_devices", json.dumps(smarthome_devices))

def toggle_device(device_id: str, force_state=None, owner_username: str = "") -> dict:
    dev = smarthome_devices.get(device_id)
    if dev is None: return None
    new_state = force_state if force_state is not None else (not dev["state"])
    dev["state"] = new_state
    save_devices()
    add_alert(
        f"SmartHome: {dev['name']} {'ON' if new_state else 'OFF'}",
        owner_username=owner_username,
    )
    return dev
