"""The library never opens a socket; the conftest blocks them for every test."""

from __future__ import annotations

import importlib
import pkgutil
import socket
import sys
from pathlib import Path

import pytest

import predictsim
from tests.conftest import NetworkBlocked

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))


def test_sockets_are_blocked() -> None:
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80))


def test_every_module_imports_and_runs_offline() -> None:
    for mod in pkgutil.walk_packages(predictsim.__path__, "predictsim."):
        importlib.import_module(mod.name)
    import fade_the_move
    import gym_random_agent
    import spread_capture

    assert spread_capture.run().fills
    assert fade_the_move.run().fills
    assert isinstance(gym_random_agent.run(), float)
