from decimal import Decimal
from fractions import Fraction

import pytest

from predictsim.units import (
    ceil_div,
    ceil_fraction,
    complement,
    floor_to,
    from_centis,
    from_micros,
    notional,
    to_centis,
    to_decimal,
    to_fraction,
    to_micros,
)


def test_conversions_are_exact() -> None:
    assert to_micros("0.42") == 420_000
    assert to_micros(0.07) == 70_000
    assert to_micros(Decimal("0.00001")) == 10
    assert to_centis("1.5") == 150
    assert from_micros(420_000) == Decimal("0.42")
    assert from_centis(150) == Decimal("1.5")
    assert to_fraction(0.07) == Fraction(7, 100)
    assert to_fraction(Fraction(1, 3)) == Fraction(1, 3)


def test_inexact_values_are_refused() -> None:
    with pytest.raises(ValueError):
        to_micros("0.0000001")
    with pytest.raises(ValueError):
        to_centis("0.001")
    with pytest.raises(TypeError):
        to_decimal(True)


def test_helpers() -> None:
    assert notional(420_000, 150) == 630_000
    with pytest.raises(ValueError):
        notional(1, 1)
    assert complement(300_000) == 700_000
    assert ceil_div(7, 2) == 4 and ceil_div(-7, 2) == -3
    assert ceil_fraction(Fraction(1, 3)) == 1
    assert floor_to(-58_639, 10_000) == -60_000
