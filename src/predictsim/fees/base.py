"""The fee-model interface shared by every venue."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from predictsim.units import CENTIS_PER_CONTRACT, MICROS_PER_DOLLAR


@dataclass(frozen=True, slots=True)
class FeeInput:
    """What a fee model sees for one fill.

    ``px`` is the price of the outcome actually traded (a NO fill carries the
    NO price), ``size`` is in centi-contracts and ``revenue`` is the fill's
    cash change before fees (negative when buying).
    """

    order_id: int
    px: int
    size: int
    is_maker: bool
    is_closing: bool
    revenue: int


@dataclass(frozen=True, slots=True)
class FeeCharge:
    """Fee on one fill, split the way Kalshi reports it. Other venues only
    use ``trade_fee``."""

    trade_fee: int
    rounding_fee: int = 0
    rebate: int = 0

    @property
    def total(self) -> int:
        """Net amount taken from cash."""
        return self.trade_fee + self.rounding_fee - self.rebate


class FeeModel(Protocol):
    """A venue fee model. Stateful models (Kalshi) keep per-order state, so
    each backtest run gets a fresh instance from :meth:`fresh`."""

    def charge(self, fill: FeeInput) -> FeeCharge:
        """Fee for a fill; may update internal state."""
        ...

    def quote(self, fill: FeeInput) -> int:
        """Upper bound on :meth:`charge` total, without changing state."""
        ...

    def settle_fee(self, value: int, size: int) -> int:
        """Fee due at settlement for ``size`` centis paying ``value`` micros each."""
        ...

    def fresh(self) -> FeeModel:
        """A new instance with the same parameters and empty state."""
        ...


def contracts_px_term(px: int, size: int) -> Fraction:
    """``C * P * (1 - P)`` in micro-dollars, exact."""
    return Fraction(size * px * (MICROS_PER_DOLLAR - px), CENTIS_PER_CONTRACT * MICROS_PER_DOLLAR)


def px_size_term(px: int, size: int) -> Fraction:
    """``px * sz`` in micro-dollars, exact."""
    return Fraction(px * size, CENTIS_PER_CONTRACT)
