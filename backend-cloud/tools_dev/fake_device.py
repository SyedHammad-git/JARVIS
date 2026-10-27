"""
Fake paired PC for gateway tests.

PowerShell (after pairing):
  py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id <id> --token <token>
  py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id <id> --token <token> --wrong-token
  py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id <id> --token <token> --never-ack
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    if os.environ.get("JARVIS_SKIP_DOTENV") != "1":
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass

import socketio


def main() -> int:
    p = argparse.ArgumentParser(description="JARVIS fake device (Socket.IO /device)")
    p.add_argument("--url", default="http://127.0.0.1:5000")
    p.add_argument("--device-id", required=True)
    p.add_argument("--token", help=argparse.SUPPRESS)
    p.add_argument("--token-env", default="JARVIS_TEST_DEVICE_TOKEN")
    p.add_argument("--never-ack", action="store_true")
    p.add_argument("--wrong-token", action="store_true")
    args = p.parse_args()

    token = args.token or os.environ.get(args.token_env, "")
    if not token:
        p.error(f"provide --token or set {args.token_env}")
    if args.wrong_token:
        token = "wrong-" + ("x" * 32)

    print("fake_device url=", args.url)
    print("fake_device device_id=", args.device_id)
    print("fake_device token_present=", bool(args.token))
    print("fake_device wrong_token=", bool(args.wrong_token), "never_ack=", bool(args.never_ack))

    sio = socketio.Client(logger=False, engineio_logger=False)

    @sio.on("command", namespace="/device")
    def on_command(data):
        print("command:", json.dumps(data, default=str)[:500])
        if args.never_ack:
            time.sleep(60)
            return None
        return {"ok": True, "message": "fake executed"}

    @sio.event(namespace="/device")
    def connect():
        print("connected namespace=/device")

    @sio.event(namespace="/device")
    def connect_error(data):
        print("connect_error:", data)
        sys.exit(2)

    @sio.event(namespace="/device")
    def disconnect():
        print("disconnected")

    try:
        sio.connect(
            args.url,
            namespaces=["/device"],
            auth={"device_id": args.device_id, "token": token},
            transports=["websocket"],
            wait_timeout=10,
        )
    except Exception as exc:
        print("connect_failed:", type(exc).__name__)
        return 1

    print("waiting for commands (Ctrl+C to quit)")
    try:
        sio.wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sio.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
