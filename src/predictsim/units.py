"""Exact unit conversion.

Everything inside PredictSim is an integer:

* price and money: micro-dollars (1e-6 dollars), so $0.42 == 420_000
* size: centi-contracts (1e-2 contracts), so 1.5 contracts == 150
* time: nanoseconds since the Unix epoch, UTC

Conversions go through :class:`decimal.Decimal` and refuse any value that is
not exactly representable in the target unit. Floats are converted through
their shortest ``repr`` (``0.07`` becomes ``Decimal("0.07")``), never through
their binary value.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import TypeAlias

MICROS_PER_DOLLAR = 1_000_000
CENTIS_PER_CONTRACT = 100
ONE_DOLLAR = MICROS_PER_DOLLAR
NANOS_PER_SECOND = 1_000_000_000

Number: TypeAlias = Decimal | str | int | float


def to_decimal(value: Number) -> Decimal:
    """Convert to Decimal exactly; floats go through their shortest repr."""
    if isinstance(value, bool):
        raise TypeError("bool is not a number here")
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def to_fraction(value: Number | Fraction) -> Fraction:
    """Convert a rate or coefficient to an exact rational."""
    if isinstance(value, Fraction):
        return value
    return Fraction(to_decimal(value))


def _scale(value: Number, factor: int, what: str) -> int:
    scaled = to_decimal(value) * factor
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{value!r} is not a whole number of {what}")
    return int(scaled)


def to_micros(dollars: Number) -> int:
    """Dollars to integer micro-dollars. ``to_micros("0.42") == 420_000``."""
    return _scale(dollars, MICROS_PER_DOLLAR, "micro-dollars")


def to_centis(contracts: Number) -> int:
    """Contracts to integer centi-contracts. ``to_centis("1.5") == 150``."""
    return _scale(contracts, CENTIS_PER_CONTRACT, "centi-contracts")


def from_micros(micros: int) -> Decimal:
    """Micro-dollars to exact Decimal dollars."""
    return Decimal(micros) / MICROS_PER_DOLLAR


def from_centis(centis: int) -> Decimal:
    """Centi-contracts to exact Decimal contracts."""
    return Decimal(centis) / CENTIS_PER_CONTRACT


def notional(px: int, size: int) -> int:
    """Exact value in micro-dollars of ``size`` centi-contracts at ``px``.

    Raises ValueError if the product is not a whole micro-dollar, which cannot
    happen on any venue grid PredictSim ships (prices with at most 4 decimals,
    or 5 decimals with whole-share sizes).
    """
    value, rest = divmod(px * size, CENTIS_PER_CONTRACT)
    if rest:
        raise ValueError(f"notional of {size} centis at {px} is not whole micros")
    return value


def complement(px: int) -> int:
    """Price of the other outcome: ``1 - px`` in micro-dollars."""
    return ONE_DOLLAR - px


def ceil_div(num: int, den: int) -> int:
    """Integer ceiling of ``num / den`` for ``den > 0``."""
    return -((-num) // den)


def ceil_fraction(value: Fraction) -> int:
    """Smallest integer >= value."""
    return ceil_div(value.numerator, value.denominator)


def floor_to(value: int, step: int) -> int:
    """Round ``value`` toward minus infinity onto a multiple of ``step``."""
    return (value // step) * step
