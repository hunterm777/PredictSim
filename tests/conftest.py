"""Shared fixtures. Every test runs with sockets blocked: any attempt to
open a network connection fails the test."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("network access is not allowed in PredictSim")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    yield
