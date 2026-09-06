"""Session-wide test guards for the whole suite.

Feature: aws-stage1-foundation, Property 13 (no non-loopback network).

Installs a socket guard so no test opens a connection to any host other than the
loopback interface. The offline contract and infra suites must never reach a real
AWS endpoint; the existing unit and integration suites are filesystem- and
in-process-only, so this guard leaves their results unchanged.
"""

import ipaddress
import socket
from collections.abc import Iterator

import pytest

_LOOPBACK_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def _is_loopback(host: str) -> bool:
    try:
        return any(ipaddress.ip_address(host) in net for net in _LOOPBACK_NETS)
    except ValueError:
        # A hostname rather than a literal address. "localhost" is loopback;
        # anything else is treated as non-loopback and blocked.
        return host in {"localhost", "localhost.localdomain"}


@pytest.fixture(autouse=True, scope="session")
def _block_non_loopback_sockets() -> Iterator[None]:
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> None:
        # AF_UNIX addresses are strings (filesystem paths); always allowed.
        if self.family == socket.AF_UNIX:
            real_connect(self, address)
            return
        host = address[0] if isinstance(address, tuple) else str(address)
        if not _is_loopback(str(host)):
            raise AssertionError(
                f"blocked non-loopback socket connect to {host!r}; "
                "tests must not reach a real network host"
            )
        real_connect(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
