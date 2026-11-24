"""Hyperliquid HIP-4 profile.

From https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets:

* Tokens: "Each outcome market consists of two sides, each with a token",
  usually Yes and No; they are separate balances, linked by merge.
* Book: "The order books of Yes and No tokens for the same outcome are merged
  to share liquidity"; "an order to buy Yes at price p is equivalent to an
  order to sell No at price 1-p", so every order maps to YES space.
* Settlement: "Yes to settleFraction quote tokens and No to
  1 - settleFraction quote tokens".
* Fees: on close or settle only; see :mod:`predictsim.fees.hip4`.

Hyperliquid's docs do not give the outcome price tick or size decimals. The
default grid (0.001 to 0.999 in 0.00001 steps) is from third-party guides
(Galaxy Research, Chainstack); set the grid and ``size_step`` from the
market's own metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from predictsim.events import Band
from predictsim.fees.hip4 import HIP4Fees
from predictsim.spec import Grid, MarketSpec
from predictsim.units import Number
from predictsim.venues.base import PositionMode


@dataclass(frozen=True, slots=True)
class HIP4Profile:
    """HIP-4 venue profile."""

    taker_rate: Number | Fraction = 0
    maker_rate: Number | Fraction = 0
    deployer_scale: Number | Fraction = "1.0"
    name: str = "hip4"
    position_mode: PositionMode = PositionMode.TOKENS
    min_notional: int = 0

    def price_ok(self, grid: Grid, px: int) -> bool:
        return grid.contains(px)

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        return size > 0 and size % spec.size_step == 0

    def fee_model(self, spec: MarketSpec) -> HIP4Fees:
        return HIP4Fees(self.taker_rate, self.maker_rate, self.deployer_scale)

    def default_grid(self) -> Grid:
        return Grid((Band(1_000, 999_000, 10),))


def btc_binary_settles_yes(
    mark0: int, t0: int, mark1: int, t1: int, settlement_time: int, target: int
) -> bool:
    """HIP-4 recurring binary rule: YES iff the mark price linearly
    interpolated at ``settlement_time`` between the HyperCore mark updates at
    ``t0`` and ``t1`` is at or above ``target``. Exact rational arithmetic."""
    if not t0 < t1 or not t0 <= settlement_time <= t1:
        raise ValueError("need t0 <= settlement_time <= t1 and t0 < t1")
    interp = mark0 + Fraction(settlement_time - t0, t1 - t0) * (mark1 - mark0)
    return interp >= target
