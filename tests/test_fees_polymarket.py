import pytest

from predictsim.fees import FeeInput, PolymarketFees
from predictsim.fees.polymarket import CATEGORY_RATES


def test_100_shares_at_half_rate_005_is_125() -> None:
    assert PolymarketFees("0.05").fee(500_000, 10_000, False) == 1_250_000


def test_makers_never_pay() -> None:
    assert PolymarketFees("0.05").charge(FeeInput(1, 500_000, 10_000, True, False, 0)).total == 0


def test_rounded_down_to_five_decimals() -> None:
    fees = PolymarketFees("0.01")
    # 0.01 x 0.01 x 0.5 x 0.5 = 0.000025 -> 0.00002
    assert fees.fee(500_000, 1, False) == 20
    # 0.01 x 0.01 x 0.01 x 0.99 = 0.00000099 -> rounds to zero
    assert fees.fee(10_000, 1, False) == 0


def test_categories() -> None:
    assert CATEGORY_RATES["crypto_btc_5m_15m_updown"] == "0.05"
    assert PolymarketFees.for_category("geopolitics").fee(500_000, 10_000, False) == 0
    assert PolymarketFees.for_category("crypto").fee(500_000, 10_000, False) == 250_000
    assert PolymarketFees.for_category("x", {"x": "0.02"}).rate == "0.02"
    with pytest.raises(KeyError):
        PolymarketFees.for_category("nope")


def test_protocol_methods() -> None:
    fees = PolymarketFees("0.05")
    inp = FeeInput(1, 500_000, 10_000, False, False, -5_000_000)
    assert fees.quote(inp) == 1_250_000
    assert fees.settle_fee(1_000_000, 100) == 0
    assert fees.fresh() is fees
