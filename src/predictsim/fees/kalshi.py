"""Kalshi fees with the documented per-order rounding accumulator.

Formula, from Kalshi's fee schedule (https://kalshi.com/docs/kalshi-fee-schedule.pdf,
"Last updated and effective: July 7, 2026"):

* taker: ``round up(M x 0.07 x C x P x (1 - P))``, M defaults to 1
* maker: ``round up(M x 0.0175 x C x P x (1 - P))``, M defaults to 0

M is the series' multiplier and sits inside the round-up. Rounding follows
https://docs.kalshi.com/getting_started/fee_rounding. Per fill:

1. ``trade_fee = ceil_6dp(model_fee)``
2. ``aligned = floor_to_precision(revenue - trade_fee)``; precision is $0.01,
   or $0.0001 for direct members
3. ``rounding_fee = (revenue - trade_fee) - aligned``
4. the rounding fee is added to the order's accumulator (kept across all of
   the order's fills, taker or maker) and rebated in whole multiples of the
   precision, capped so the fill's net fee is never negative.

There is no settlement fee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from predictsim.fees.base import FeeCharge, FeeInput, contracts_px_term
from predictsim.units import Number, ceil_fraction, floor_to, to_fraction

CENT = 10_000
DIRECT_PRECISION = 100
TAKER_COEF = Fraction(7, 100)
MAKER_COEF = Fraction(175, 10_000)


@dataclass(slots=True)
class KalshiFees:
    """Kalshi fee model with the series' taker and maker multipliers."""

    taker_multiplier: Number | Fraction = 1
    maker_multiplier: Number | Fraction = 0
    direct_member: bool = False
    _acc: dict[int, int] = field(default_factory=dict, repr=False)
    _rates: tuple[Fraction, Fraction] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        taker = TAKER_COEF * to_fraction(self.taker_multiplier)
        maker = MAKER_COEF * to_fraction(self.maker_multiplier)
        if taker < 0 or maker < 0:
            raise ValueError("Kalshi fee multipliers must be >= 0")
        self._rates = (taker, maker)

    @property
    def precision(self) -> int:
        """Balance precision in micro-dollars."""
        return DIRECT_PRECISION if self.direct_member else CENT

    def trade_fee(self, px: int, size: int, is_maker: bool) -> int:
        """Step 1: the model fee rounded up to a whole micro-dollar."""
        rate = self._rates[is_maker]
        return ceil_fraction(rate * contracts_px_term(px, size)) if rate else 0

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
        return KalshiFees(self.taker_multiplier, self.maker_multiplier, self.direct_member)
