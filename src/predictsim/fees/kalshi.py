"""Kalshi fees with the documented per-order rounding accumulator.

Source: https://docs.kalshi.com/getting_started/fee_rounding (checked Nov 23, 2026)
and the fee formula ``round up(0.07 x C x P x (1 - P))`` from Kalshi's CFTC
filing, where any market multiplier sits inside the round-up.

Per fill:

1. ``trade_fee = ceil_to_$0.000001(coef * M * C * P * (1 - P))``
2. ``aligned = floor_to_precision(revenue - trade_fee)``; precision is $0.01,
   or $0.0001 for direct members
3. ``rounding_fee = (revenue - trade_fee) - aligned``
4. the rounding fee is added to the order's accumulator, and whole multiples of
   the precision are rebated, capped so the net fee is never negative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from predictsim.fees.base import FeeCharge, FeeInput, contracts_px_term
from predictsim.units import Number, ceil_fraction, floor_to, to_fraction

CENT = 10_000
DIRECT_PRECISION = 100


@dataclass(slots=True)
class KalshiFees:
    """Kalshi fee model. ``maker_fees`` is True only for series that list
    maker fees; otherwise makers pay no trade fee."""

    taker_coef: Number | Fraction = "0.07"
    maker_coef: Number | Fraction = "0.0175"
    multiplier: Number | Fraction = 1
    maker_fees: bool = False
    direct_member: bool = False
    _acc: dict[int, int] = field(default_factory=dict, repr=False)

    @property
    def precision(self) -> int:
        """Balance precision in micro-dollars."""
        return DIRECT_PRECISION if self.direct_member else CENT

    def trade_fee(self, px: int, size: int, is_maker: bool) -> int:
        """Step 1: the model fee rounded up to a whole micro-dollar."""
        if is_maker and not self.maker_fees:
            return 0
        coef = to_fraction(self.maker_coef if is_maker else self.taker_coef)
        return ceil_fraction(coef * to_fraction(self.multiplier) * contracts_px_term(px, size))

    def _pre_rebate(self, fill: FeeInput) -> tuple[int, int]:
        fee = self.trade_fee(fill.px, fill.size, fill.is_maker)
        raw = fill.revenue - fee
        return fee, raw - floor_to(raw, self.precision)

    def charge(self, fill: FeeInput) -> FeeCharge:
        fee, rounding = self._pre_rebate(fill)
        acc = self._acc.get(fill.order_id, 0) + rounding
        rebate = min(floor_to(acc, self.precision), fee + rounding)
        self._acc[fill.order_id] = acc - rebate
        return FeeCharge(trade_fee=fee, rounding_fee=rounding, rebate=rebate)

    def quote(self, fill: FeeInput) -> int:
        fee, rounding = self._pre_rebate(fill)
        return fee + rounding

    def accumulated(self, order_id: int) -> int:
        """Rounding carried forward on an order, in micro-dollars."""
        return self._acc.get(order_id, 0)

    def settle_fee(self, value: int, size: int) -> int:
        return 0

    def fresh(self) -> KalshiFees:
        return KalshiFees(
            self.taker_coef, self.maker_coef, self.multiplier, self.maker_fees, self.direct_member
        )
