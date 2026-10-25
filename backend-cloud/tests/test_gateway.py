"""call_device edge cases: offline, timeout, invalid ack."""
import unittest
import time
from unittest.mock import patch

from socketio.exceptions import TimeoutError as SocketIOTimeout

from devices.gateway import call_device, is_online, _bind, _unbind_sid
from devices.pairing import hash_token, issue_device, validate_device_token, revoke_device
from extensions import socketio


class CallDeviceTests(unittest.TestCase):
    def setUp(self):
        active_device = patch("devices.gateway.get_device_status_cached", return_value={"revoked": 0})
        active_device.start()
        self.addCleanup(active_device.stop)

    def test_offline_when_unmapped(self):
        self.assertFalse(is_online("dev_nobody"))
        out = call_device("dev_nobody", "open_app", {"target": "notepad"})
        self.assertEqual(out, {"ok": False, "error": "device_offline"})

    def test_timeout(self):
        _bind("dev_to", "sid_to")
        try:
            with patch("devices.gateway.socketio.call", side_effect=SocketIOTimeout("t")):
                out = call_device("dev_to", "open_app", {"target": "notepad"}, timeout=1)
            self.assertEqual(out, {"ok": False, "error": "device_timeout"})
        finally:
            _unbind_sid("sid_to")

    def test_ack_must_be_dict_with_ok(self):
        _bind("dev_ack", "sid_ack")
        try:
            with patch("devices.gateway.socketio.call", return_value="nope"):
                self.assertEqual(
                    call_device("dev_ack", "open_app", {}),
                    {"ok": False, "error": "device_timeout"},
                )
            with patch("devices.gateway.socketio.call", return_value={"message": "missing ok"}):
                self.assertEqual(
                    call_device("dev_ack", "open_app", {}),
                    {"ok": False, "error": "device_timeout"},
                )
            with patch("devices.gateway.socketio.call",
                       return_value={"ok": True, "message": "fake executed"}):
                out = call_device("dev_ack", "open_app", {"target": "notepad"})
            self.assertTrue(out["ok"])
            self.assertEqual(out["message"], "fake executed")
        finally:
            _unbind_sid("sid_ack")

    def test_payload_shape(self):
        _bind("dev_pay", "sid_pay")
        try:
            with patch("devices.gateway.socketio.call",
                       return_value={"ok": True, "message": "x"}) as mock_call:
                call_device("dev_pay", "open_app", {"target": "notepad"})
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
        _bind("dev_revoked", "sid_revoked")
        try:
            with patch("devices.gateway.get_device_status_cached", return_value={"revoked": 1}), \
                 patch("devices.gateway.socketio.call") as mock_call:
                self.assertEqual(
                    call_device("dev_revoked", "open_app", {"target": "notepad"}),
                    {"ok": False, "error": "device_revoked"},
                )
            mock_call.assert_not_called()
        finally:
            _unbind_sid("sid_revoked")


class TokenValidateTests(unittest.TestCase):
    def test_wrong_token_rejected(self):
        device_id, token = issue_device("gw-pc")
        self.assertIsNotNone(validate_device_token(device_id, token))
        self.assertIsNone(validate_device_token(device_id, "wrong-" + token))
        self.assertIsNone(validate_device_token("dev_missing", token))
        revoke_device(device_id)
        self.assertIsNone(validate_device_token(device_id, token))
        self.assertEqual(len(hash_token(token)), 64)


class LiveRevocationTests(unittest.TestCase):
    def test_revoke_disconnects_socket_and_refuses_commands(self):
        from app import create_app

        app = create_app(testing=True)

        device_id, token = issue_device("live-revoke-test")
        client = socketio.test_client(
            app,
            namespace="/device",
            auth={"device_id": device_id, "token": token},
        )
        try:
            self.assertTrue(client.is_connected("/device"))
            started = time.monotonic()
            self.assertTrue(revoke_device(device_id))
            self.assertFalse(client.is_connected("/device"))
            self.assertLess(time.monotonic() - started, 2.0)
            response = app.test_client().get(
                "/api/device/status", query_string={"device_id": device_id}
            )
            self.assertTrue(response.get_json()["revoked"])
            self.assertEqual(
                call_device(device_id, "open_app", {"target": "notepad"}),
                {"ok": False, "error": "device_revoked"},
            )
        finally:
            if client.is_connected("/device"):
                client.disconnect(namespace="/device")


if __name__ == "__main__":
    unittest.main()
