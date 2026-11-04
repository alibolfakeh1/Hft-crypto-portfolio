"""No test in this suite may reach a network, whatever it builds. Every test runs behind this guard."""

from __future__ import annotations

import socket
from typing import NoReturn

import pytest


def _refuse(*_: object, **__: object) -> NoReturn:
    raise AssertionError("a test tried to use the network")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Below every HTTP library, so that a fake handler left out of an opener fails here and contacts
    nothing."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
