"""
J.A.R.V.I.S v17.M — Smart Home Module
FIXED: L4 removed duplicate TUYA_OK (now imported from config)
"""
import json, logging
from database import cfg_get, cfg_set
from auth import add_alert
from config import TUYA_OK   # ✅ FIX L4: single source of truth

log = logging.getLogger("jarvis.smarthome")

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

def _load_tuya_devices() -> dict:
    raw = cfg_get("tuya_devices","")
    if raw:
        try: return json.loads(raw)
        except Exception: pass
    return {}

smarthome_devices = _load_devices()
TUYA_DEVICES      = _load_tuya_devices()

def save_devices():
    cfg_set("smarthome_devices", json.dumps(smarthome_devices))

def save_tuya_devices():
    cfg_set("tuya_devices", json.dumps(TUYA_DEVICES))

def tuya_control(device_id: str, action) -> tuple:
    if not TUYA_OK:
        return False, "tuyapy not installed — pip install tuyapy"
    dev = TUYA_DEVICES.get(device_id)
    if not dev:
        return False, f"Tuya device '{device_id}' not configured"
    try:
        import tuyapy
        d = tuyapy.TuyaDevice(
            device_id=dev["device_id"], device_key=dev["device_key"], device_ip=dev.get("ip","")
        )
        d.turn_on() if action in (True,"on",1,"1") else d.turn_off()
        return True, "OK"
    except Exception as e:
        log.error("Tuya control error (%s): %s", device_id, e)
        return False, str(e)

def mqtt_publish(topic: str, payload) -> bool:
    try:
        import paho.mqtt.publish as mqtt_pub
        host = cfg_get("mqtt_host","localhost")
        port = int(cfg_get("mqtt_port","1883"))
        msg  = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        mqtt_pub.single(topic, payload=msg, hostname=host, port=port)
        return True
    except ImportError:
        log.warning("paho-mqtt not installed — pip install paho-mqtt")
        return False
    except Exception as e:
        log.error("MQTT publish error: %s", e)
        return False

def toggle_device(device_id: str, force_state=None) -> dict:
    dev = smarthome_devices.get(device_id)
    if dev is None: return None
    new_state = force_state if force_state is not None else (not dev["state"])
    dev["state"] = new_state
    save_devices()
    add_alert(f"SmartHome: {dev['name']} {'ON' if new_state else 'OFF'}")
    if device_id in TUYA_DEVICES:
        ok, msg = tuya_control(device_id, new_state)
        if not ok: log.warning("Tuya error for %s: %s", device_id, msg)
    return dev
