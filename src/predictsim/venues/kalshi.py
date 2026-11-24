"""Kalshi profile.

* Book: "two arrays of bids: ``yes_dollars`` for YES positions and
  ``no_dollars`` for NO positions"; "A NO BID at price Y is equivalent to a
  YES ASK at price ($1.00 - Y)".
  https://docs.kalshi.com/getting_started/orderbook_responses
* Orders: one YES book, bid or ask (Create Order V2: "single-book bid/ask
  side"). Buying NO at q is the same order as selling YES at 1 - q.
* Positions: one signed position per market, positive for YES and negative
  for NO (an FCM transfer of 5 NO contracts is ``position_centicount`` -500),
  so YES and NO net against each other.
* Grid: per-market ``price_ranges`` bands; whole cents are always valid.
  https://docs.kalshi.com/getting_started/fixed_point_migration
* Sizes: fractional contracts at 0.01 granularity.
* Fees: :mod:`predictsim.fees.kalshi`; multipliers are set per series.
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
    """Kalshi venue profile. Multipliers come from Kalshi's fee schedule for
    the market's series: taker defaults to 1, maker to 0."""

    taker_multiplier: Number | Fraction = 1
    maker_multiplier: Number | Fraction = 0
    direct_member: bool = False
    name: str = "kalshi"
    position_mode: PositionMode = PositionMode.NET
    min_notional: int = 0

    def price_ok(self, grid: Grid, px: int) -> bool:
        return grid.contains(px) or (0 < px < ONE_DOLLAR and px % CENT == 0)

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        return size > 0 and size % spec.size_step == 0

    def fee_model(self, spec: MarketSpec) -> KalshiFees:
        return KalshiFees(self.taker_multiplier, self.maker_multiplier, self.direct_member)

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
