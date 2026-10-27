"""Pairing: plaintext token is returned once; only sha256 is stored."""
import unittest
from flask import Flask
import pytest

from app.devices.pairing import hash_token, issue_device, list_devices, revoke_device
from app.db import db_read
from app import security
from app.devices import http as devices_http


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
        self.assertTrue(revoke_device(device_id, "pairing-test-owner"))
        rows = db_read("SELECT revoked FROM devices WHERE device_id=?", (device_id,))
        self.assertEqual(int(rows[0]["revoked"]), 1)
        self.assertFalse(revoke_device("dev_does_not_exist", "pairing-test-owner"))


def test_pair_code_rate_limits_enforce_global_and_per_ip_caps(monkeypatch):
    monkeypatch.setattr(devices_http, "db_write", lambda *_args: True)
    results = iter([
        {"attempts": devices_http._PAIR_GLOBAL_LIMIT + 1, "locked_until": 0},
        {"attempts": 1, "locked_until": 0},
        {"attempts": 1, "locked_until": 0},
        {"attempts": devices_http._PAIR_IP_LIMIT + 1, "locked_until": 0},
    ])
    monkeypatch.setattr(devices_http, "db_write_returning", lambda *_args: [next(results)])

    assert not devices_http._check_pair_request("203.0.113.10", 100.0)
    assert not devices_http._check_pair_request("203.0.113.10", 101.0)


def test_pair_code_failure_lockout_starts_after_five_failures(monkeypatch):
    writes = []
    monkeypatch.setattr(devices_http, "db_write_returning", lambda *_args: [{"failures": 5}])
    monkeypatch.setattr(devices_http, "db_write", lambda sql, params: writes.append((sql, params)) or True)

    devices_http._record_pair_failure("203.0.113.11", 100.0)

    assert writes[-1] == (
        "UPDATE pair_code_rate_limits SET locked_until=? WHERE rate_key=?",
        (100.0 + devices_http._PAIR_LOCKOUT_SECONDS, devices_http._pair_ip_rate_key("203.0.113.11")),
    )
    assert "203.0.113.11" not in writes[-1][1][1]


def test_pair_code_limiter_receives_proxy_resolved_client_ip(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    app = Flask("pair-proxy-rate-limit-test")
    security.configure_proxy(app)
    captured = []
    monkeypatch.setattr(
        devices_http, "_check_pair_request",
        lambda client_ip, _now: captured.append(client_ip) or False,
    )
    app.register_blueprint(devices_http.devices_bp)

    response = app.test_client().post(
        "/pairing/redeem-code",
        json={"code": "ABCDEFGH"},
        headers={"X-Forwarded-For": "203.0.113.12"},
    )

    assert response.status_code == 429
    assert captured == ["203.0.113.12"]


if __name__ == "__main__":
    unittest.main()
