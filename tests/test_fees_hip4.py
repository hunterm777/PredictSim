from fractions import Fraction

from predictsim.fees import FeeInput, HIP4Fees


def test_effective_rate_matches_chainstack_example() -> None:
    fees = HIP4Fees("0.0006", 0, deployer_scale="1.0", referral_discount="0.04")
    assert fees.effective_rate(False) == Fraction("0.001152")
    # a closing taker sell of 1,000 shares at 0.50
    assert fees.fee(500_000, 100_000, False, True) == 576_000


def test_opening_buy_pays_nothing() -> None:
    fees = HIP4Fees("0.0006", "0.0002")
    assert fees.charge(FeeInput(1, 500_000, 10_000, False, False, -5_000_000)).total == 0


def test_maker_close_and_rounding_up() -> None:
    fees = HIP4Fees("0.0006", "0.0002", deployer_scale=0)
    assert fees.fee(500_000, 100, True, True) == 100  # 0.0002 x $0.50
    assert fees.fee(333_330, 100, False, True) == 200  # 199.998 rounds up
    assert fees.quote(FeeInput(1, 500_000, 100, True, True, 500_000)) == 100


def test_settlement_fee_uses_taker_rate() -> None:
    fees = HIP4Fees("0.0006", 0, referral_discount="0.04")
    assert fees.settle_fee(1_000_000, 300) == 3_456
    assert fees.settle_fee(0, 300) == 0
    assert fees.fresh() is fees
