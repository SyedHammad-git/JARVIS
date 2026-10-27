"""Connect a temporary loopback device over Socket.IO WebSocket and report status only."""
from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    args = parser.parse_args(argv)
    parsed = urlsplit(args.url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("WEBSOCKET=FAIL (loopback URL required)")
        return 2

    os.environ.setdefault("DB_BACKEND", "sqlite")
    os.environ.setdefault("JARVIS_SKIP_DOTENV", "1")
    from app.devices.pairing import issue_device, revoke_device
    import socketio

    owner = "clerk:local-smoke-test"
    device_id, token = issue_device("Local smoke device", owner)
    client = socketio.Client(logger=False, engineio_logger=False)
    connected = False
    try:
        client.connect(
            args.url,
            namespaces=["/device"],
            auth={"device_id": device_id, "token": token},
            transports=["websocket"],
            wait_timeout=10,
        )
        connected = client.connected
        print("WEBSOCKET=PASS" if connected else "WEBSOCKET=FAIL")
        return 0 if connected else 1
    except Exception as exc:
        print(f"WEBSOCKET=FAIL ({type(exc).__name__})")
        return 1
    finally:
        if client.connected:
            client.disconnect()
        revoke_device(device_id, owner)


if __name__ == "__main__":
    raise SystemExit(main())
