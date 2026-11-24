"""Hyperliquid HIP-4 outcome-market fees.

From https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees ("Outcome
tokens"): "Outcome trading only charges fees when closing or settling, not
when opening outcome positions." "Outcome trading does not support rebates."
"Users who would receive rebates for spot and perp trading pay zero fees on
maker orders." Fee-paying volume is ``fee_paying_px * sz``.

From https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions
(marked "Testnet-only"): users "pay the base outcome trading fee rate times
``scale + max(scale, 1)``"; scale 1 gives 2x, scale 0.5 gives 1.5x, scale 0
gives 1x.

The HIP-4 page says "Fees are currently zero for outcome markets for initial
testing", so the default rates are 0.

Not published, so chosen by PredictSim: fees round up to a whole micro-dollar,
and settlement is charged at the taker rate on the settlement value
(``settle_fraction * sz`` for YES).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from predictsim.fees.base import FeeCharge, FeeInput, px_size_term
from predictsim.units import Number, ceil_fraction, to_fraction


def deployer_factor(scale: Fraction) -> Fraction:
    """Multiple of the base rate a user pays: ``scale + max(scale, 1)``."""
    return scale + max(scale, Fraction(1))


@dataclass(frozen=True, slots=True)
class HIP4Fees:
    """HIP-4 fee model. Rates are the user's base outcome rates; a negative
    maker rate (a would-be rebate) pays zero."""

    taker_rate: Number | Fraction
    maker_rate: Number | Fraction
    deployer_scale: Number | Fraction = "1.0"
    _rates: tuple[Fraction, Fraction] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        scale = to_fraction(self.deployer_scale)
        if scale < 0:
            raise ValueError("deployer_scale must be >= 0")
        mult = deployer_factor(scale)
        taker = max(to_fraction(self.taker_rate), Fraction(0)) * mult
        maker = max(to_fraction(self.maker_rate), Fraction(0)) * mult
        object.__setattr__(self, "_rates", (taker, maker))

    def effective_rate(self, is_maker: bool) -> Fraction:
        """Rate applied to ``px * sz``."""
        return self._rates[is_maker]

    def fee(self, px: int, size: int, is_maker: bool, is_closing: bool) -> int:
        rate = self._rates[is_maker]
        if not is_closing or not rate:
            return 0
        return ceil_fraction(rate * px_size_term(px, size))

    def charge(self, fill: FeeInput) -> FeeCharge:
        return FeeCharge(self.fee(fill.px, fill.size, fill.is_maker, fill.is_closing))

    def quote(self, fill: FeeInput) -> int:
        return self.fee(fill.px, fill.size, fill.is_maker, fill.is_closing)

    def settle_fee(self, value: int, size: int) -> int:
        rate = self._rates[False]
        return ceil_fraction(rate * px_size_term(value, size)) if rate else 0

    def fresh(self) -> HIP4Fees:
        return self
