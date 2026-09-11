"""Network guard.

Feature: aws-stage1-foundation, Property 13.

Asserts the session-wide socket guard (tests/conftest.py) is active: a deliberate
non-loopback connect attempt raises, naming the destination, while a loopback
connect is permitted.
"""

import socket

import pytest


def test_non_loopback_connect_is_blocked() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AssertionError, match="non-loopback"):
            sock.connect(("93.184.216.34", 80))  # example.com, never actually reached
    finally:
        sock.close()


def test_loopback_connect_is_permitted() -> None:
    # Bind a loopback listener and confirm the guard lets the connection through.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(("127.0.0.1", port))  # must not raise
    finally:
        client.close()
        listener.close()
