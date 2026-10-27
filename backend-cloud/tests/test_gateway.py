"""call_device edge cases: offline, timeout, invalid ack."""
import unittest
import time
from unittest.mock import patch

from socketio.exceptions import TimeoutError as SocketIOTimeout

from app.devices.gateway import call_device, is_online, _bind, _unbind_sid
from app.devices.pairing import (
    hash_token,
    issue_device,
    validate_device_token,
    revoke_device,
    set_device_scopes,
)
from app.extensions import socketio


class CallDeviceTests(unittest.TestCase):
    def _owned_device(self, name):
        owner = "gateway-test-owner"
        device_id, token = issue_device(name, owner)
        scopes = {
            "allow_open_app": True,
            "allow_camera": False,
            "allow_notify": False,
            "allow_lock": False,
            "allow_system_stats": False,
        }
        self.assertTrue(set_device_scopes(device_id, owner, scopes))
        return device_id, token, owner

    def test_offline_when_unmapped(self):
        self.assertFalse(is_online("dev_nobody"))
        out = call_device("dev_nobody", "open_app", {"target": "notepad"})
        self.assertEqual(out, {"ok": False, "error": "device_offline"})

    def test_timeout(self):
        device_id, _token, owner = self._owned_device("timeout-pc")
        _bind(device_id, "sid_to")
        try:
            with patch("app.devices.gateway.socketio.call", side_effect=SocketIOTimeout("t")):
                out = call_device(
                    device_id, "open_app", {"target": "notepad"}, timeout=1,
                    owner_username=owner,
                )
            self.assertEqual(out, {"ok": False, "error": "device_timeout"})
        finally:
            _unbind_sid("sid_to")

    def test_ack_must_be_dict_with_ok(self):
        device_id, _token, owner = self._owned_device("ack-pc")
        _bind(device_id, "sid_ack")
        try:
            with patch("app.devices.gateway.socketio.call", return_value="nope"):
                self.assertEqual(
                    call_device(device_id, "open_app", {}, owner_username=owner),
                    {"ok": False, "error": "device_timeout"},
                )
            with patch("app.devices.gateway.socketio.call", return_value={"message": "missing ok"}):
                self.assertEqual(
                    call_device(device_id, "open_app", {}, owner_username=owner),
                    {"ok": False, "error": "device_timeout"},
                )
            with patch("app.devices.gateway.socketio.call",
                       return_value={"ok": True, "message": "fake executed"}):
                out = call_device(
                    device_id, "open_app", {"target": "notepad"}, owner_username=owner,
                )
            self.assertTrue(out["ok"])
            self.assertEqual(out["message"], "fake executed")
        finally:
            _unbind_sid("sid_ack")

    def test_payload_shape(self):
        device_id, _token, owner = self._owned_device("payload-pc")
        _bind(device_id, "sid_pay")
        try:
            with patch("app.devices.gateway.socketio.call",
                       return_value={"ok": True, "message": "x"}) as mock_call:
                call_device(
                    device_id, "open_app", {"target": "notepad"}, owner_username=owner,
                )
            args, kwargs = mock_call.call_args
            self.assertEqual(args[0], "command")
            payload = args[1]
            self.assertEqual(payload["action"], "open_app")
            self.assertEqual(payload["args"], {"target": "notepad"})
            self.assertIn("id", payload)
            self.assertEqual(kwargs.get("namespace"), "/device")
            self.assertEqual(kwargs.get("to"), "sid_pay")
        finally:
            _unbind_sid("sid_pay")

    def test_revoked_device_is_refused_before_emit(self):
        device_id, _token, owner = self._owned_device("revoked-pc")
        _bind(device_id, "sid_revoked")
        try:
            self.assertTrue(revoke_device(device_id, owner))
            with patch("app.devices.gateway.socketio.call") as mock_call:
                self.assertEqual(
                    call_device(
                        device_id, "open_app", {"target": "notepad"}, owner_username=owner,
                    ),
                    {"ok": False, "error": "device_revoked"},
                )
            mock_call.assert_not_called()
        finally:
            _unbind_sid("sid_revoked")


class TokenValidateTests(unittest.TestCase):
    def test_wrong_token_rejected(self):
        from app import create_app

        device_id, token = issue_device("gw-pc", "wrong-token-owner")
        self.assertIsNotNone(validate_device_token(device_id, token))
        self.assertIsNone(validate_device_token(device_id, "wrong-" + token))
        self.assertIsNone(validate_device_token("dev_missing", token))
        app = create_app(testing=True)
        bad_client = socketio.test_client(
            app,
            namespace="/device",
            auth={"device_id": device_id, "token": "wrong-" + token},
        )
        self.assertFalse(bad_client.is_connected("/device"))
        good_client = socketio.test_client(
            app,
            namespace="/device",
            auth={"device_id": device_id, "token": token},
        )
        try:
            self.assertTrue(good_client.is_connected("/device"))
        finally:
            if good_client.is_connected("/device"):
                good_client.disconnect(namespace="/device")
        revoke_device(device_id, "clerk:wrong-token-owner")
        self.assertIsNone(validate_device_token(device_id, token))
        self.assertEqual(len(hash_token(token)), 64)


class LiveRevocationTests(unittest.TestCase):
    def test_revoke_disconnects_socket_and_refuses_commands(self):
        from app import create_app

        app = create_app(testing=True)

        owner = "live-revoke-owner"
        device_id, token = issue_device("live-revoke-test", owner)
        client = socketio.test_client(
            app,
            namespace="/device",
            auth={"device_id": device_id, "token": token},
        )
        try:
            self.assertTrue(client.is_connected("/device"))
            started = time.monotonic()
            self.assertTrue(revoke_device(device_id, owner))
            self.assertFalse(client.is_connected("/device"))
            self.assertLess(time.monotonic() - started, 2.0)
            self.assertEqual(
                call_device(
                    device_id, "open_app", {"target": "notepad"},
                    owner_username=owner,
                ),
                {"ok": False, "error": "device_revoked"},
            )
        finally:
            if client.is_connected("/device"):
                client.disconnect(namespace="/device")


if __name__ == "__main__":
    unittest.main()
