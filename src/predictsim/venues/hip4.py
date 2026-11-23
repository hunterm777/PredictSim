"""Hyperliquid HIP-4 profile (as of Nov 23, 2026).

* Book: YES and NO tokens with merged books: buying YES at P is selling NO at
  1 - P, so every order maps to YES space.
* Grid: bounded 0.001 to 0.999 (Galaxy Research); mainnet quotes up to 5
  decimals (Chainstack).
* Sizes: whole shares.
* Fees: spot-tier rate on close or settle only; see :mod:`predictsim.fees.hip4`.
* Settlement: YES pays ``settleFraction``, NO pays ``1 - settleFraction``.
  https://docs.chainstack.com/docs/hyperliquid-hip4-outcome-markets-trading
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from predictsim.events import Band
from predictsim.fees.hip4 import HIP4Fees
from predictsim.spec import Grid, MarketSpec
from predictsim.units import CENTIS_PER_CONTRACT, Number
from predictsim.venues.base import PositionMode


@dataclass(frozen=True, slots=True)
class HIP4Profile:
    """HIP-4 venue profile."""

    taker_rate: Number | Fraction = 0
    maker_rate: Number | Fraction = 0
    deployer_scale: Number | Fraction = "1.0"
    referral_discount: Number | Fraction = 0
    name: str = "hip4"
    position_mode: PositionMode = PositionMode.TOKENS

    def price_ok(self, grid: Grid, px: int) -> bool:
        return grid.contains(px)

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        return size > 0 and size % spec.size_step == 0 and size % CENTIS_PER_CONTRACT == 0

    def fee_model(self, spec: MarketSpec) -> HIP4Fees:
        return HIP4Fees(self.taker_rate, self.maker_rate, self.deployer_scale, self.referral_discount)

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
