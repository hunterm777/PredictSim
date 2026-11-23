"""Polymarket fees.

Source: https://docs.polymarket.com/trading/fees (checked Nov 23, 2026):
``fee = C x feeRate x p x (1 - p)``, takers only, rounded to 5 decimal places;
the smallest fee charged is 0.00001 and anything smaller rounds to zero. The
docs do not say which way to round, so PredictSim truncates (rounds down),
which is what "anything smaller rounds to zero" implies.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from predictsim.fees.base import FeeCharge, FeeInput, contracts_px_term
from predictsim.units import Number, floor_to, to_fraction

FEE_PRECISION = 10  # $0.00001 in micro-dollars

CATEGORY_RATES: dict[str, str] = {
    "crypto_btc_5m_15m_updown": "0.05",
    "crypto": "0.01",
    "sports": "0.05",
    "finance": "0.05",
    "tech": "0.05",
    "politics_elections": "0.05",
    "combos": "0.05",
    "other": "0.05",
    "politics": "0.01",
    "economics": "0.01",
    "culture": "0.01",
    "weather": "0.01",
    "mentions": "0.01",
    "geopolitics": "0",
}
"""Taker rates by category, as listed in the PRD (Nov 2026)."""


@dataclass(frozen=True, slots=True)
class PolymarketFees:
    """Polymarket taker fee at ``rate``; makers never pay."""

    rate: Number | Fraction

    @classmethod
    def for_category(cls, category: str, rates: dict[str, str] | None = None) -> PolymarketFees:
        table = CATEGORY_RATES if rates is None else rates
        if category not in table:
            raise KeyError(f"unknown Polymarket fee category {category!r}")
        return cls(table[category])

    def fee(self, px: int, size: int, is_maker: bool) -> int:
        if is_maker:
            return 0
        exact = to_fraction(self.rate) * contracts_px_term(px, size)
        whole = exact.numerator // exact.denominator
        return floor_to(whole, FEE_PRECISION)

    def charge(self, fill: FeeInput) -> FeeCharge:
        return FeeCharge(self.fee(fill.px, fill.size, fill.is_maker))

    def quote(self, fill: FeeInput) -> int:
        return self.fee(fill.px, fill.size, fill.is_maker)

    def settle_fee(self, value: int, size: int) -> int:
        return 0

    def fresh(self) -> PolymarketFees:
        return self
