"""Kalshi fee acceptance tests from the PRD table and Kalshi's fee-rounding docs."""

from predictsim.fees import FeeInput, KalshiFees


def fill(oid: int, px: int, size: int, maker: bool = False, revenue: int | None = None) -> FeeInput:
    rev = -(px * size // 100) if revenue is None else revenue
    return FeeInput(oid, px, size, maker, False, rev)


def test_taker_100_at_50c_is_175() -> None:
    assert KalshiFees().charge(fill(1, 500_000, 10_000)).total == 1_750_000


def test_maker_100_at_50c_is_044() -> None:
    charge = KalshiFees(maker_fees=True).charge(fill(1, 500_000, 10_000, maker=True))
    assert charge.trade_fee == 437_500  # 0.0175 x 100 x 0.25, exact
    assert charge.rounding_fee == 2_500  # balance floored to the cent
    assert charge.total == 440_000


def test_maker_pays_nothing_without_maker_fees() -> None:
    assert KalshiFees().charge(fill(1, 500_000, 10_000, maker=True)).total == 0


def test_taker_100_at_10c_is_063() -> None:
    assert KalshiFees().charge(fill(1, 100_000, 10_000)).total == 630_000


def test_rounding_example_from_docs() -> None:
    # revenue -$0.055 (1 contract at $0.055), model fee $0.00363825
    charge = KalshiFees().charge(fill(1, 55_000, 100, revenue=-55_000))
    assert charge.trade_fee == 3_639
    assert -55_000 - charge.trade_fee - charge.rounding_fee == -60_000
    assert charge.rounding_fee == 1_361
    assert charge.trade_fee + charge.rounding_fee == 5_000


def test_accumulator_rebates_after_third_fill() -> None:
    fees = KalshiFees()
    # 1 contract at $0.311: trade fee $0.015000, balance overpays $0.004
    one = fill(9, 311_000, 100)
    first, second, third = (fees.charge(one) for _ in range(3))
    assert [c.trade_fee for c in (first, second, third)] == [15_000] * 3
    assert [c.rounding_fee for c in (first, second, third)] == [4_000] * 3
    assert first.rebate == second.rebate == 0
    assert third.rebate == 10_000
    assert fees.accumulated(9) == 2_000
    assert [c.total for c in (first, second, third)] == [19_000, 19_000, 9_000]


def test_accumulator_is_per_order() -> None:
    fees = KalshiFees()
    for oid in (1, 2, 3):
        assert fees.charge(fill(oid, 311_000, 100)).rebate == 0
    assert fees.accumulated(1) == fees.accumulated(3) == 4_000


def test_rebate_never_makes_net_fee_negative() -> None:
    fees = KalshiFees()
    # zero-fee maker fills, each overpaying $0.004 on balance rounding
    overpay = FeeInput(9, 500_000, 1, True, False, -6_000)
    charges = [fees.charge(overpay) for _ in range(3)]
    assert all(c.total >= 0 for c in charges)
    assert charges[2].rebate == 4_000  # capped at that fill's fee
    assert fees.accumulated(9) == 8_000


def test_direct_members_round_to_hundredth_cent() -> None:
    charge = KalshiFees(direct_member=True).charge(fill(1, 55_000, 100, revenue=-55_000))
    assert charge.trade_fee == 3_639 and charge.rounding_fee == 61


def test_multiplier_sits_inside_round_up() -> None:
    # CFTC filing: INX markets use round up(0.035 x C x P x (1-P)); $0.88 at $0.50
    half = KalshiFees(multiplier="0.5")
    assert half.charge(fill(1, 500_000, 10_000)).total == 880_000
    assert half.trade_fee(100_000, 10_000, False) == 315_000


def test_quote_and_fresh() -> None:
    fees = KalshiFees()
    assert fees.quote(fill(1, 500_000, 10_000)) == 1_750_000
    assert fees.accumulated(1) == 0
    assert fees.fresh().accumulated(1) == 0
    assert fees.settle_fee(1_000_000, 100) == 0
