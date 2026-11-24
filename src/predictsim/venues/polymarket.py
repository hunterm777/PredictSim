"""Polymarket profile.

* Tokens: "Both represent Yes and No outcomes as ERC-1155 balances"; YES and
  NO are separate balances. "Splitting 1 pUSD creates 1 Yes position and 1 No
  position"; merging returns 1 pUSD for each YES + NO pair.
  https://docs.polymarket.com/concepts/positions-tokens
* Book: a buy of YES at 0.60 and a buy of NO at 0.40 match ("1 pUSD of
  collateral creates a complete set"), so both books are one YES-space book.
  https://docs.polymarket.com/concepts/prices-orderbook
* Per market (https://docs.polymarket.com/market-data/market-details):
  ``orderPriceMinTickSize`` of 0.1, 0.01, 0.005, 0.0025, 0.001 or 0.0001
  (give it as the grid; a change mid-market is a GridChange event);
  ``orderMinSize`` in USDC ("The CLOB rejects orders below this threshold");
  ``feesEnabled`` and ``feeSchedule`` (see :mod:`predictsim.fees.polymarket`).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from predictsim.fees.polymarket import PolymarketFees
from predictsim.spec import Grid, MarketSpec, uniform_grid
from predictsim.units import Number
from predictsim.venues.base import PositionMode


@dataclass(frozen=True, slots=True)
class PolymarketProfile:
    """Polymarket venue profile for one market: its ``feeSchedule``
    (``fee_rate``, ``fee_exponent``, ``taker_only``), ``feesEnabled`` and
    ``orderMinSize`` (``min_notional``, in micro-dollars)."""

    fee_rate: Number | Fraction
    fee_exponent: int = 1
    taker_only: bool = True
    fees_enabled: bool = True
    min_notional: int = 0
    name: str = "polymarket"
    position_mode: PositionMode = PositionMode.TOKENS

    def price_ok(self, grid: Grid, px: int) -> bool:
        return grid.contains(px)

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        return size > 0 and size % spec.size_step == 0

    def fee_model(self, spec: MarketSpec) -> PolymarketFees:
        return PolymarketFees(self.fee_rate, self.fee_exponent, self.taker_only, self.fees_enabled)

    def default_grid(self) -> Grid:
        return uniform_grid(10_000)
