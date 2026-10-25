"""Pairing: plaintext token is returned once; only sha256 is stored."""
import unittest

from app.devices.pairing import hash_token, issue_device, list_devices, revoke_device
from app.db import db_read


class PairingTests(unittest.TestCase):
    def test_token_shown_once_only_hash_stored(self):
        owner = "pairing-test-owner"
        device_id, token = issue_device("unit-pc", owner)
        self.assertTrue(device_id.startswith("dev_"))
        self.assertGreaterEqual(len(token), 32)
        rows = db_read(
            "SELECT token_hash, name, revoked FROM devices WHERE device_id=?",
            (device_id,),
        )
        self.assertEqual(len(rows), 1)
        stored = rows[0]["token_hash"]
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, hash_token(token))
        listed = [d for d in list_devices(owner) if d["device_id"] == device_id]
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])
        self.assertNotIn("token_hash", listed[0])
        self.assertEqual(listed[0]["name"], "unit-pc")

    def test_revoke_marks_row(self):
        device_id, _token = issue_device("revoke-pc", "pairing-test-owner")
        self.assertTrue(revoke_device(device_id))
        rows = db_read("SELECT revoked FROM devices WHERE device_id=?", (device_id,))
        self.assertEqual(int(rows[0]["revoked"]), 1)
        self.assertFalse(revoke_device("dev_does_not_exist"))


if __name__ == "__main__":
    unittest.main()
