# SPDX-License-Identifier: MIT
"""Process-local loopback-only network policy; no system firewall changes."""

import ipaddress
import os
import socket


def install_offline_policy():
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        os.environ[name] = "1"
    state = {"enabled": True, "blocked_attempts": 0}
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo

    def allow(host):
        if host in (None, "localhost", b"localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False

    def check(address):
        host = address[0] if isinstance(address, tuple) else address
        if not allow(host):
            state["blocked_attempts"] += 1
            raise PermissionError("Voice service permits only loopback networking")

    def guarded_connect(sock, address):
        check(address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check(address)
        return connect_ex(sock, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        check(host)
        return getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo
    return state
