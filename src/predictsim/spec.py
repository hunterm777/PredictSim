"""Market specification and price grids."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING

from predictsim.events import Band
from predictsim.units import ONE_DOLLAR

if TYPE_CHECKING:
    from predictsim.fees.base import FeeModel
    from predictsim.venues.base import VenueProfile


@dataclass(frozen=True, slots=True)
class Grid:
    """A price grid made of bands. A price is valid if it lies on any band's
    step lattice and strictly between $0 and $1. Bands may share endpoints."""

    bands: tuple[Band, ...]

    def __post_init__(self) -> None:
        if not self.bands:
            raise ValueError("a grid needs at least one band")

    def contains(self, px: int) -> bool:
        if not 0 < px < ONE_DOLLAR:
            return False
        return any(b.start <= px <= b.end and (px - b.start) % b.step == 0 for b in self.bands)

    def lowest(self) -> int:
        """Lowest valid price."""
        return min(self._band_low(b) for b in self.bands if self._band_low(b) > 0)

    def highest(self) -> int:
        """Highest valid price."""
        return max(self._band_high(b) for b in self.bands if self._band_high(b) > 0)

    @staticmethod
    def _band_low(b: Band) -> int:
        px = b.start if b.start > 0 else b.step
        return px if px <= b.end and px < ONE_DOLLAR else 0

    @staticmethod
    def _band_high(b: Band) -> int:
        top = b.end if b.end < ONE_DOLLAR else ONE_DOLLAR - 1
        px = b.start + ((top - b.start) // b.step) * b.step
        return px if px > 0 else 0

    def snap_down(self, px: int) -> int | None:
        """Highest valid price <= px, or None."""
        best: int | None = None
        for b in self.bands:
            if px < b.start:
                continue
            top = min(px, b.end, ONE_DOLLAR - 1)
            cand = b.start + ((top - b.start) // b.step) * b.step
            if cand > 0 and (best is None or cand > best):
                best = cand
        return best


def uniform_grid(step: int, low: int | None = None, high: int | None = None) -> Grid:
    """One band from ``low`` (default ``step``) to ``high`` (default $1 - step)."""
    lo = step if low is None else low
    hi = ONE_DOLLAR - step if high is None else high
    return Grid((Band(lo, hi, step),))


@dataclass(frozen=True, slots=True)
class MarketSpec:
    """Everything the simulator needs to know about one binary market.

    ``fee_category`` picks the Polymarket rate; ``fee_multiplier`` scales the
    Kalshi formula. ``fees`` overrides the venue's fee model entirely (for
    example with :class:`predictsim.fees.custom.CustomFees`).
    """

    market_id: str
    venue: VenueProfile
    open_ts: int
    close_ts: int
    grid: Grid
    size_step: int
    min_size: int
    fee_category: str | None = None
    fee_multiplier: Fraction = field(default_factory=lambda: Fraction(1))
    fees: FeeModel | None = None

    def __post_init__(self) -> None:
        if self.close_ts < self.open_ts:
            raise ValueError("close_ts is before open_ts")
        if self.size_step <= 0 or self.min_size <= 0:
            raise ValueError("size_step and min_size must be positive")

    def fee_model(self) -> FeeModel:
        """A fresh fee model for one run of this market."""
        return self.fees.fresh() if self.fees is not None else self.venue.fee_model(self)
