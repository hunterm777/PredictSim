"""Polymarket profile (as of Nov 23, 2026).

* Book: one book per token; YES and NO are separate tokens. Supply the YES
  token's book (a NO bid at q is a YES ask at 1 - q).
* Grid: per-market ``tick_size`` of 0.1, 0.01, 0.001 or 0.0001, which can
  change mid-market (supply a GridChange event).
  https://docs.polymarket.com/trading/place-orders
* Sizes: shares with 2 decimals; per-market ``min_order_size``.
* Fees: taker only, rate by category. https://docs.polymarket.com/trading/fees
* Positions: separate YES/NO tokens with split and merge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from predictsim.fees.polymarket import CATEGORY_RATES, PolymarketFees
from predictsim.spec import Grid, MarketSpec, uniform_grid
from predictsim.venues.base import PositionMode


@dataclass(frozen=True, slots=True)
class PolymarketProfile:
    """Polymarket venue profile. ``rates`` maps fee category to taker rate."""

    rates: dict[str, str] = field(default_factory=lambda: dict(CATEGORY_RATES))
    name: str = "polymarket"
    position_mode: PositionMode = PositionMode.TOKENS

    def price_ok(self, grid: Grid, px: int) -> bool:
        return grid.contains(px)

    def size_ok(self, spec: MarketSpec, size: int) -> bool:
        return size > 0 and size % spec.size_step == 0

    def fee_model(self, spec: MarketSpec) -> PolymarketFees:
        if spec.fee_category is None:
            raise ValueError("Polymarket markets need a fee_category")
        return PolymarketFees.for_category(spec.fee_category, self.rates)

    def default_grid(self) -> Grid:
        return uniform_grid(10_000)
