"""HIP-4 fee tests from Hyperliquid's fees and HIP-4 deployer-actions pages."""

from fractions import Fraction

import pytest

from predictsim.fees import FeeInput, HIP4Fees
from predictsim.fees.hip4 import deployer_factor


def test_prd_example_rate() -> None:
    # PRD: taker 0.0006, 4% referral discount, deployer scale 1.0 -> 0.001152
    fees = HIP4Fees("0.0006", 0, deployer_scale="1.0", referral_discount="0.04")
    assert fees.effective_rate(False) == Fraction("0.001152")
    # a closing taker sell of 1,000 shares at 0.50
    assert fees.fee(500_000, 100_000, False, True) == 576_000


@pytest.mark.parametrize(
    ("scale", "multiple"), [("0", 1), ("0.25", "1.25"), ("0.5", "1.5"), ("1", 2), ("3", 6), ("10", 20)]
)
def test_deployer_scale_table(scale: str, multiple: object) -> None:
    # users pay the base rate times scale + max(scale, 1)
    assert deployer_factor(Fraction(scale)) == Fraction(str(multiple))


def test_opening_buy_pays_nothing() -> None:
    fees = HIP4Fees("0.0006", "0.0002")
    assert fees.charge(FeeInput(1, 500_000, 10_000, False, False, -5_000_000)).total == 0


def test_maker_close_and_rounding_up() -> None:
    fees = HIP4Fees("0.0006", "0.0002", deployer_scale=0)
    assert fees.fee(500_000, 100, True, True) == 100  # 0.0002 x $0.50
    assert fees.fee(333_330, 100, False, True) == 200  # 199.998 rounds up
    assert fees.quote(FeeInput(1, 500_000, 100, True, True, 500_000)) == 100


def test_would_be_rebate_pays_zero_and_zero_default() -> None:
    assert HIP4Fees("0.0006", "-0.0001").fee(500_000, 100, True, True) == 0
    assert HIP4Fees(0, 0).settle_fee(1_000_000, 300) == 0
    with pytest.raises(ValueError):
        HIP4Fees(0, 0, deployer_scale=-1)


def test_settlement_fee_uses_taker_rate() -> None:
    fees = HIP4Fees("0.0006", 0, referral_discount="0.04")
    assert fees.settle_fee(1_000_000, 300) == 3_456
    assert fees.settle_fee(0, 300) == 0
    assert fees.fresh() is fees
