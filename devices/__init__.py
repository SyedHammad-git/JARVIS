"""Paired-PC device gateway (Socket.IO /device namespace)."""
from devices.pairing import issue_device, list_devices, revoke_device, hash_token
from devices.gateway import is_online, call_device, disconnect_device

__all__ = [
    "issue_device", "list_devices", "revoke_device", "hash_token",
    "is_online", "call_device", "disconnect_device",
]
