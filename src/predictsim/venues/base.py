"""The venue-profile interface: grid, sizes, fees and position mode."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from predictsim.fees.base import FeeModel
    from predictsim.spec import Grid, MarketSpec


class PositionMode(StrEnum):
    """``net``: one signed position per market (Kalshi). ``tokens``: separate
    YES and NO token balances with explicit split and merge."""

    NET = "net"
    TOKENS = "tokens"


class VenueProfile(Protocol):
    """Everything venue-specific. Profiles are plain dataclasses whose fields
    can all be overridden, because venues change rules often."""

    @property
    def name(self) -> str: ...

    @property
    def position_mode(self) -> PositionMode: ...

    def price_ok(self, grid: Grid, px: int) -> bool:
        """Is ``px`` (YES micros) a valid price on ``grid``?"""
        ...

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        """Is ``size`` (centis) a valid order size, ignoring the minimum?"""
        ...

    def fee_model(self, spec: MarketSpec) -> FeeModel:
        """A fresh fee model for ``spec``."""
        ...

    def default_grid(self) -> Grid:
        """The grid most markets on this venue use."""
        ...
