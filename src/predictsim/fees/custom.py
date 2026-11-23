"""User-defined fees."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from predictsim.fees.base import FeeCharge, FeeInput


@dataclass(frozen=True, slots=True)
class CustomFees:
    """Fees from any function of the fill, returning integer micro-dollars.
    No fee is charged at settlement."""

    fn: Callable[[FeeInput], int]

    def charge(self, fill: FeeInput) -> FeeCharge:
        fee = self.fn(fill)
        if not isinstance(fee, int) or isinstance(fee, bool):
            raise TypeError("CustomFees function must return an int of micro-dollars")
        return FeeCharge(fee)

    def quote(self, fill: FeeInput) -> int:
        return self.charge(fill).total

    def settle_fee(self, value: int, size: int) -> int:
        return 0

    def fresh(self) -> CustomFees:
        return self
