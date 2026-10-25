from __future__ import annotations

import getpass
import sys

import pyotp

from app import load_environment
from app.authentication import create_user
from app.db import db_scalar, init_db


def main() -> int:
    load_environment()
    init_db()
    if int(db_scalar("SELECT COUNT(*) FROM users") or 0):
        print("A user already exists. Manage accounts through the authenticated API.")
        return 1

    username = input("Username: ").strip()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1

    secret = pyotp.random_base32()
    try:
        if not create_user(username, password, secret):
            print("User creation failed.")
            return 1
    except ValueError as exc:
        print(str(exc))
        return 1

    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="JARVIS")
    print("User created. Add this TOTP URI to your authenticator now:")
    print(uri)
    print("The TOTP secret is stored server-side; keep the authenticator enrolled securely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
