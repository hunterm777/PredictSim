"""Hyperliquid HIP-4 outcome-market fees.

Source: https://docs.chainstack.com/docs/hyperliquid-hip4-outcome-markets-trading
(checked Nov 23, 2026). Fees are charged only when closing or settling, never
when opening, at the user's spot rate after any referral discount, on
``px * sz``. A deployer fee scale of 1.0 charges twice the rate, so the
multiplier is ``1 + deployer_scale``. There are no maker rebates.

Rounding is not published; PredictSim rounds up to a whole micro-dollar. The
rate used at settlement is not published either; PredictSim uses the taker
rate on the settlement value.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from predictsim.fees.base import FeeCharge, FeeInput, px_size_term
from predictsim.units import Number, ceil_fraction, to_fraction


@dataclass(frozen=True, slots=True)
class HIP4Fees:
    """HIP-4 fee model."""

    taker_rate: Number | Fraction
    maker_rate: Number | Fraction
    deployer_scale: Number | Fraction = "1.0"
    referral_discount: Number | Fraction = 0

    def effective_rate(self, is_maker: bool) -> Fraction:
        """Rate applied to ``px * sz``."""
        rate = to_fraction(self.maker_rate if is_maker else self.taker_rate)
        scale = 1 + to_fraction(self.deployer_scale)
        return scale * rate * (1 - to_fraction(self.referral_discount))

    def fee(self, px: int, size: int, is_maker: bool, is_closing: bool) -> int:
        if not is_closing:
            return 0
        return ceil_fraction(self.effective_rate(is_maker) * px_size_term(px, size))

    def charge(self, fill: FeeInput) -> FeeCharge:
        return FeeCharge(self.fee(fill.px, fill.size, fill.is_maker, fill.is_closing))

    def quote(self, fill: FeeInput) -> int:
        return self.fee(fill.px, fill.size, fill.is_maker, fill.is_closing)

    def settle_fee(self, value: int, size: int) -> int:
        return ceil_fraction(self.effective_rate(False) * px_size_term(value, size))

    def fresh(self) -> HIP4Fees:
        return self
