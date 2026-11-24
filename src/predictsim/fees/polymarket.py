"""Polymarket fees.

Formula, from https://docs.polymarket.com/trading/fees:
``fee = C x feeRate x p x (1 - p)``. "Fees are rounded to 5 decimal places."
"The smallest fee charged is 0.00001 USDC. Anything smaller rounds to zero."
The docs do not give a rounding direction; PredictSim rounds down, which is
what "anything smaller rounds to zero" implies.

The parameters are per market, from the market's ``feesEnabled`` and
``feeSchedule`` {``rate``, ``exponent``, ``takerOnly``}
(https://docs.polymarket.com/market-data/market-details). ``exponent`` is
"applied to the price component of the fee curve", read here as
``(p x (1 - p)) ** exponent``; the docs' example and the fees page formula
use 1. With ``takerOnly`` true, "makers pay no fee".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from predictsim.fees.base import FeeCharge, FeeInput
from predictsim.units import CENTIS_PER_CONTRACT, MICROS_PER_DOLLAR, Number, floor_to, to_fraction

FEE_PRECISION = 10  # $0.00001 in micro-dollars


@dataclass(frozen=True, slots=True)
class PolymarketFees:
    """One market's Polymarket fee schedule."""

    rate: Number | Fraction
    exponent: int = 1
    taker_only: bool = True
    enabled: bool = True
    _rate: Fraction = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rate = to_fraction(self.rate)
        if rate < 0 or self.exponent < 0:
            raise ValueError("fee rate and exponent must be >= 0")
        object.__setattr__(self, "_rate", rate if self.enabled else Fraction(0))

    def fee(self, px: int, size: int, is_maker: bool) -> int:
        if not self._rate or (is_maker and self.taker_only):
            return 0
        curve = Fraction(px * (MICROS_PER_DOLLAR - px), MICROS_PER_DOLLAR * MICROS_PER_DOLLAR)
        exact = self._rate * size * MICROS_PER_DOLLAR * curve**self.exponent / CENTIS_PER_CONTRACT
        return floor_to(exact.numerator // exact.denominator, FEE_PRECISION)

    def charge(self, fill: FeeInput) -> FeeCharge:
        return FeeCharge(self.fee(fill.px, fill.size, fill.is_maker))

    def quote(self, fill: FeeInput) -> int:
        return self.fee(fill.px, fill.size, fill.is_maker)

    def settle_fee(self, value: int, size: int) -> int:
        return 0

    def fresh(self) -> PolymarketFees:
        return self
