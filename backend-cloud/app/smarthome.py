"""
J.A.R.V.I.S v17.M — Smart Home Module
FIXED: L4 removed duplicate TUYA_OK (now imported from config)
"""
import json
from app.db import db_read, db_write, db_write_many, register_owner
from app.auth import add_alert

_DEFAULT_DEVICES = {
    "light_1": {"name":"Main Light",   "state":False,"type":"light","icon":"💡","room":"Living Room"},
    "light_2": {"name":"Bedroom Light","state":False,"type":"light","icon":"💡","room":"Bedroom"},
    "fan_1":   {"name":"Ceiling Fan",  "state":False,"type":"fan",  "icon":"🌀","room":"Living Room"},
    "ac_1":    {"name":"AC Unit",      "state":False,"type":"ac",   "icon":"❄️","room":"Bedroom"},
    "plug_1":  {"name":"Smart Plug",   "state":False,"type":"plug", "icon":"🔌","room":"Office"},
}


def get_devices(owner_username: str) -> dict:
    if not owner_username:
        return {}
    register_owner(owner_username)
    rows = db_read(
        "SELECT device_id,name,state,type,icon,room FROM smarthome_devices "
        "WHERE owner_username=? ORDER BY device_id",
        (owner_username,),
    )
    if rows:
        return {
            row["device_id"]: {
                "name": row["name"],
                "state": bool(row["state"]),
                "type": row["type"],
                "icon": row["icon"],
                "room": row["room"],
            }
            for row in rows
        }
    initialized = db_read(
        "SELECT smarthome_initialized FROM user_owners WHERE owner_username=?",
        (owner_username,),
    )
    if initialized and initialized[0]["smarthome_initialized"]:
        return {}
    save_devices(owner_username, _DEFAULT_DEVICES)
    db_write(
        "UPDATE user_owners SET smarthome_initialized=1 WHERE owner_username=?",
        (owner_username,),
    )
    return {key: dict(value) for key, value in _DEFAULT_DEVICES.items()}


def save_devices(owner_username: str, devices: dict) -> None:
    if not owner_username:
        return
    statements = [
        ("DELETE FROM smarthome_devices WHERE owner_username=?", (owner_username,)),
    ]
    statements.extend(
        (
            "INSERT INTO smarthome_devices(owner_username,device_id,name,state,type,icon,room) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                owner_username,
                str(device_id),
                str(device.get("name") or "Device"),
                int(bool(device.get("state"))),
                str(device.get("type") or "switch"),
                str(device.get("icon") or ""),
                str(device.get("room") or ""),
            ),
        )
        for device_id, device in devices.items()
    )
    if not db_write_many(statements):
        raise RuntimeError("smarthome_storage_failed")
    db_write(
        "UPDATE user_owners SET smarthome_initialized=1 WHERE owner_username=?",
        (owner_username,),
    )

def add_device(owner_username: str, device_id: str, device: dict) -> None:
    devices = get_devices(owner_username)
    devices[device_id] = device
    save_devices(owner_username, devices)


def remove_device(owner_username: str, device_id: str) -> dict | None:
    devices = get_devices(owner_username)
    removed = devices.pop(device_id, None)
    if removed is not None:
        save_devices(owner_username, devices)
    return removed


def import_legacy_devices(owner_username: str, raw: str) -> int:
    try:
        devices = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        devices = {}
    if not isinstance(devices, dict):
        devices = {}
    normalized = {
        str(device_id): value
        for device_id, value in devices.items()
        if isinstance(value, dict)
    }
    if not normalized:
        return 0
    statements = [
        (
            "INSERT INTO smarthome_devices(owner_username,device_id,name,state,type,icon,room) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner_username,device_id) DO NOTHING",
            (
                owner_username,
                device_id,
                str(device.get("name") or "Device"),
                int(bool(device.get("state"))),
                str(device.get("type") or "switch"),
                str(device.get("icon") or ""),
                str(device.get("room") or ""),
            ),
        )
        for device_id, device in normalized.items()
    ]
    if not db_write_many(statements):
        raise RuntimeError("smarthome_storage_failed")
    db_write(
        "UPDATE user_owners SET smarthome_initialized=1 WHERE owner_username=?",
        (owner_username,),
    )
    return len(normalized)


def toggle_device(device_id: str, force_state=None, owner_username: str = "") -> dict | None:
    devices = get_devices(owner_username)
    dev = devices.get(device_id)
    if dev is None: return None
    new_state = force_state if force_state is not None else (not dev["state"])
    dev["state"] = new_state
    save_devices(owner_username, devices)
    add_alert(
        f"SmartHome: {dev['name']} {'ON' if new_state else 'OFF'}",
        owner_username=owner_username,
    )
    return dev
