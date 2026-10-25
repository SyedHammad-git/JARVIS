"""
Live Socket.IO gateway checks (wrong token, revoke, ack, timeout).
Loads .env first. Never prints secrets or tokens.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
if os.environ.get("JARVIS_SKIP_DOTENV") != "1":
    load_dotenv(str(ROOT / ".env"), override=False)

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("JARVIS_HOST", "127.0.0.1")
os.environ.setdefault("PYTHONUTF8", "1")

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_VERIFY_PORT", "5010"))
URL = f"http://{HOST}:{PORT}"


def _client():
    import socketio
    return socketio.Client(logger=False, engineio_logger=False)


def _connect(device_id: str, token: str, never_ack: bool = False, wait: float = 8):
    sio = _client()
    got = {"cmd": None}

    @sio.on("command", namespace="/device")
    def on_command(data):
        got["cmd"] = data
        print("command_action=", (data or {}).get("action"), "target=", (data or {}).get("args", {}).get("target"))
        if never_ack:
            time.sleep(60)
            return None
        return {"ok": True, "message": "fake executed"}

    try:
        sio.connect(
            URL,
            namespaces=["/device"],
            auth={"device_id": device_id, "token": token},
            transports=["websocket"],
            wait_timeout=wait,
        )
        return sio, got, None
    except Exception as exc:
        return None, got, type(exc).__name__


def main() -> int:
    print("dotenv_loaded", True)
    print("GROQ_KEY", bool(os.environ.get("GROQ_KEY")))
    print("GEMINI_KEY", bool(os.environ.get("GEMINI_KEY")))
    print("OPENROUTER_KEY", bool(os.environ.get("OPENROUTER_KEY")))
    from app import create_app
    from app.extensions import socketio
    from app.devices.pairing import issue_device, revoke_device, set_device_scopes, validate_device_token
    from app.devices.gateway import call_device, is_online

    app = create_app()

    ready = threading.Event()

    def _run():
        ready.set()
        socketio.run(
            app, host=HOST, port=PORT, debug=False,
            use_reloader=False, allow_unsafe_werkzeug=True,
        )

    threading.Thread(target=_run, daemon=True, name="VerifySio").start()
    time.sleep(1.5)
    print("server_url", URL)

    results = {}

    owner = "verify-gateway-owner"
    device_id, token = issue_device("verify-pc", owner)
    set_device_scopes(device_id, owner, {
        "allow_open_app": True,
        "allow_camera": False,
        "allow_notify": False,
        "allow_lock": False,
        "allow_system_stats": False,
    })
    print("paired_device_id_prefix", device_id[:8])
    print("token_present", bool(token))

    # a) wrong token rejected
    sio_bad, _, err = _connect(device_id, "wrong-" + token)
    results["wrong_token_rejected"] = sio_bad is None
    print("a_wrong_token_rejected", results["wrong_token_rejected"], "err", err)
    if sio_bad:
        sio_bad.disconnect()

    # a2) good token connects
    sio_ok, got, err_ok = _connect(device_id, token)
    results["good_token_connected"] = sio_ok is not None and is_online(device_id)
    print("a_good_token_connected", results["good_token_connected"], "err", err_ok)

    # c) open_app ack
    ack = call_device(
        device_id, "open_app", {"target": "notepad"}, timeout=10,
        owner_username=owner,
    )
    results["open_app_ack"] = bool(ack.get("ok")) and ack.get("message") == "fake executed"
    results["open_app_payload"] = (got.get("cmd") or {}).get("action") == "open_app"
    print("c_ack", ack.get("ok"), "payload_open_app", results["open_app_payload"])
    if sio_ok:
        sio_ok.disconnect()
        time.sleep(0.4)

    # a3) revoke kicks and cannot reconnect
    sio_live, _, _ = _connect(device_id, token)
    print("pre_revoke_online", is_online(device_id))
    revoke_device(device_id)
    time.sleep(0.5)
    results["revoked_offline"] = not is_online(device_id)
    print("a_revoked_offline", results["revoked_offline"])
    if sio_live:
        try:
            sio_live.disconnect()
        except Exception:
            pass
    sio_rev, _, err_rev = _connect(device_id, token)
    results["revoked_cannot_reconnect"] = sio_rev is None
    print("a_revoked_cannot_reconnect", results["revoked_cannot_reconnect"], "err", err_rev)
    if sio_rev:
        sio_rev.disconnect()

    # d) never-ack -> device_timeout ~20s
    device_id2, token2 = issue_device("timeout-pc", owner)
    set_device_scopes(device_id2, owner, {
        "allow_open_app": True,
        "allow_camera": False,
        "allow_notify": False,
        "allow_lock": False,
        "allow_system_stats": False,
    })
    sio_na, _, err_na = _connect(device_id2, token2, never_ack=True)
    print("d_never_ack_connected", sio_na is not None, "err", err_na)
    t0 = time.time()
    to_ack = call_device(
        device_id2, "open_app", {"target": "notepad"}, timeout=20,
        owner_username=owner,
    )
    elapsed = time.time() - t0
    results["device_timeout"] = to_ack.get("error") == "device_timeout" and 15 <= elapsed <= 28
    print("d_timeout", to_ack, "elapsed_s", round(elapsed, 1))
    if sio_na:
        try:
            sio_na.disconnect()
        except Exception:
            pass

    # b) offline call
    off = call_device("dev_missing", "open_app", {"target": "notepad"})
    results["device_offline"] = off.get("error") == "device_offline"
    print("b_device_offline", results["device_offline"])

    print("RESULTS", json.dumps(results))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
