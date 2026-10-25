from __future__ import annotations

import ipaddress
import logging
import os
import socket

log = logging.getLogger("jarvis.config")


def resolve_bind_host(host: str | None = None, allow_public: str | None = None) -> str:
    bind_host = (host if host is not None else os.environ.get("JARVIS_HOST", "127.0.0.1")).strip()
    if not bind_host:
        raise RuntimeError("JARVIS_HOST must be a valid loopback address")

    try:
        resolved_addresses = {ipaddress.ip_address(bind_host.strip("[]").split("%")[0])}
    except ValueError:
        try:
            results = socket.getaddrinfo(bind_host, None, type=socket.SOCK_STREAM)
            resolved_addresses = {
                ipaddress.ip_address(result[4][0].split("%")[0]) for result in results
            }
        except (OSError, ValueError) as exc:
            raise RuntimeError("JARVIS_HOST could not be resolved; refusing to start") from exc

    if resolved_addresses and all(address.is_loopback for address in resolved_addresses):
        return bind_host

    public_allowed = allow_public if allow_public is not None else os.environ.get("ALLOW_PUBLIC_BIND", "")
    if public_allowed != "1":
        raise RuntimeError(
            "Refusing non-loopback bind. Set JARVIS_HOST=127.0.0.1 in backend-cloud/.env. "
            "To explicitly allow public access, set ALLOW_PUBLIC_BIND=1 on a trusted network."
        )

    log.warning(
        "PUBLIC BIND ENABLED: JARVIS_HOST is not loopback and the API has no authentication"
    )
    return bind_host
