"""Kalshi profile (as of Nov 23, 2026).

* Book: two bid-only arrays, YES and NO; YES ask = $1 - best NO bid.
  https://docs.kalshi.com/getting_started/orderbook_responses
* Grid: per-market ``price_ranges`` bands; whole cents are always valid.
  https://docs.kalshi.com/getting_started/fixed_point_migration
* Sizes: fractional contracts at 0.01 granularity.
* Positions: net per market.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from predictsim.events import BookSide, Delta, Level, Snapshot
from predictsim.fees.kalshi import KalshiFees
from predictsim.spec import Grid, MarketSpec, uniform_grid
from predictsim.units import ONE_DOLLAR, Number, complement
from predictsim.venues.base import PositionMode

CENT = 10_000


@dataclass(frozen=True, slots=True)
class KalshiProfile:
    """Kalshi venue profile. ``maker_fees`` should be True only for series
    that list maker fees."""

    taker_coef: Number | Fraction = "0.07"
    maker_coef: Number | Fraction = "0.0175"
    maker_fees: bool = False
    direct_member: bool = False
    name: str = "kalshi"
    position_mode: PositionMode = PositionMode.NET

    def price_ok(self, grid: Grid, px: int) -> bool:
        return grid.contains(px) or (0 < px < ONE_DOLLAR and px % CENT == 0)

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        return size > 0 and size % spec.size_step == 0

    def fee_model(self, spec: MarketSpec) -> KalshiFees:
        return KalshiFees(
            taker_coef=self.taker_coef,
            maker_coef=self.maker_coef,
            multiplier=spec.fee_multiplier,
            maker_fees=self.maker_fees,
            direct_member=self.direct_member,
        )

    def default_grid(self) -> Grid:
        return uniform_grid(CENT)


def snapshot_from_kalshi(ts: int, yes_bids: Iterable[Level], no_bids: Iterable[Level]) -> Snapshot:
    """Convert Kalshi's YES and NO bid arrays to a YES-space snapshot."""
    asks = tuple(sorted((complement(px), sz) for px, sz in no_bids))
    return Snapshot(ts, tuple(sorted(yes_bids)), asks)


def delta_from_kalshi(ts: int, outcome: str, px: int, new_sz: int) -> Delta:
    """Convert a Kalshi level update on the ``"yes"`` or ``"no"`` bid array."""
    if outcome == "yes":
        return Delta(ts, BookSide.BID, px, new_sz)
    if outcome == "no":
        return Delta(ts, BookSide.ASK, complement(px), new_sz)
    raise ValueError(f"outcome must be 'yes' or 'no', got {outcome!r}")
