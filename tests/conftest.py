"""Test-wide guard: the test suite never reaches the network (CS302 M3: business-rule tests
never call a live model).

Every model, EHR and drug port in the tests is a fake (tests/compose.py, tests/fakes), and
the HTTP transports get fake posters. This guard makes that a rule instead of a habit:
any attempt to resolve or connect to a non-local address fails the test immediately with
LiveNetworkBlocked. Loopback stays allowed (the port check talks to 127.0.0.1).
"""

import socket

LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"}


class LiveNetworkBlocked(RuntimeError):
    pass


def _host(address) -> str:
    return str(address[0] if isinstance(address, tuple) else address)


def _check(host: str) -> None:
    if host not in LOCAL and not host.startswith("127."):
        raise LiveNetworkBlocked(f"tests must not reach the network (tried {host}); use a fake")


_real_getaddrinfo, _real_connect, _real_connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex


def _getaddrinfo(host, *args, **kwargs):
    _check(str(host))
    return _real_getaddrinfo(host, *args, **kwargs)


def _connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(_host(address))
    return _real_connect(self, address)


def _connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(_host(address))
    return _real_connect_ex(self, address)


socket.getaddrinfo = _getaddrinfo
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex


# Through an HTTP(S) proxy the socket only sees the proxy (often on 127.0.0.1), so also check
# the real destination where http.client knows it (urllib, and so every model transport, uses it).
import http.client  # noqa: E402

_real_http_connect = http.client.HTTPConnection.connect


def _http_connect(self):
    _check(str(getattr(self, "_tunnel_host", None) or self.host))
    return _real_http_connect(self)


http.client.HTTPConnection.connect = _http_connect      # HTTPSConnection inherits and calls this first
