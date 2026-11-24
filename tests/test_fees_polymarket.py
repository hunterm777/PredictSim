"""Polymarket fee tests: docs.polymarket.com/trading/fees and the per-market
feeSchedule from docs.polymarket.com/market-data/market-details."""

import pytest

from predictsim.fees import FeeInput, PolymarketFees


def test_100_shares_at_half_rate_005_is_125() -> None:
    assert PolymarketFees("0.05").fee(500_000, 10_000, False) == 1_250_000


def test_makers_never_pay_when_taker_only() -> None:
    assert PolymarketFees("0.05").charge(FeeInput(1, 500_000, 10_000, True, False, 0)).total == 0
    assert PolymarketFees("0.05", taker_only=False).fee(500_000, 10_000, True) == 1_250_000


def test_rounded_down_to_five_decimals() -> None:
    fees = PolymarketFees("0.01")
    # 0.01 x 0.01 x 0.5 x 0.5 = 0.000025 -> 0.00002
    assert fees.fee(500_000, 1, False) == 20
    # 0.01 x 0.01 x 0.01 x 0.99 = 0.00000099 -> rounds to zero
    assert fees.fee(10_000, 1, False) == 0


def test_exponent_applies_to_price_component() -> None:
    # 100 x 0.05 x (0.5 x 0.5) ** 2 = 0.3125
    assert PolymarketFees("0.05", exponent=2).fee(500_000, 10_000, False) == 312_500
    assert PolymarketFees("0.05", exponent=0).fee(500_000, 10_000, False) == 5_000_000


def test_fees_disabled_or_zero_rate() -> None:
    assert PolymarketFees("0.05", enabled=False).fee(500_000, 10_000, False) == 0
    assert PolymarketFees(0).fee(500_000, 10_000, False) == 0
    with pytest.raises(ValueError):
        PolymarketFees("-0.01")
    with pytest.raises(ValueError):
        PolymarketFees("0.01", exponent=-1)


def test_protocol_methods() -> None:
    fees = PolymarketFees("0.05")
    inp = FeeInput(1, 500_000, 10_000, False, False, -5_000_000)
    assert fees.quote(inp) == 1_250_000
    assert fees.settle_fee(1_000_000, 100) == 0
    assert fees.fresh() is fees
