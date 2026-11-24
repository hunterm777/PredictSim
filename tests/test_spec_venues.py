from fractions import Fraction

import pytest

from predictsim.events import Band, BookSide
from predictsim.fees import HIP4Fees, KalshiFees, PolymarketFees
from predictsim.fees.custom import CustomFees
from predictsim.spec import Grid, MarketSpec, uniform_grid
from predictsim.venues import HIP4Profile, KalshiProfile, PolymarketProfile, PositionMode
from predictsim.venues.hip4 import btc_binary_settles_yes
from predictsim.venues.kalshi import delta_from_kalshi, snapshot_from_kalshi

TAPERED = Grid((Band(0, 100_000, 1_000), Band(100_000, 900_000, 10_000), Band(900_000, 1_000_000, 1_000)))


def test_grid_membership_and_bounds() -> None:
    assert TAPERED.contains(1_000) and TAPERED.contains(100_000) and TAPERED.contains(999_000)
    assert not TAPERED.contains(0) and not TAPERED.contains(1_000_000)
    assert not TAPERED.contains(105_000) and TAPERED.contains(95_000)
    assert TAPERED.lowest() == 1_000 and TAPERED.highest() == 999_000
    assert TAPERED.snap_down(105_500) == 100_000 and TAPERED.snap_down(0) is None
    assert uniform_grid(10_000).highest() == 990_000
    with pytest.raises(ValueError):
        Grid(())
    with pytest.raises(ValueError):
        Band(10, 5, 1)


def test_kalshi_profile() -> None:
    k = KalshiProfile()
    grid = Grid((Band(0, 100_000, 1_000),))
    assert k.price_ok(grid, 2_000) and k.price_ok(grid, 500_000)  # whole cents always valid
    assert not k.price_ok(grid, 505_000)
    spec = MarketSpec("k", KalshiProfile(taker_multiplier=Fraction(1, 2)), 0, 1, grid, 1, 1)
    fees = spec.fee_model()
    assert isinstance(fees, KalshiFees) and fees.taker_multiplier == Fraction(1, 2)
    assert fees.maker_multiplier == 0 and k.min_notional == 0
    assert k.size_ok(spec, 1) and not k.size_ok(spec, 0)
    assert k.position_mode is PositionMode.NET and k.default_grid().contains(10_000)


def test_kalshi_book_conversion() -> None:
    snap = snapshot_from_kalshi(5, [(400_000, 10)], [(550_000, 3), (500_000, 7)])
    assert snap.bids == ((400_000, 10),) and snap.asks == ((450_000, 3), (500_000, 7))
    assert delta_from_kalshi(1, "no", 300_000, 5).side is BookSide.ASK
    assert delta_from_kalshi(1, "no", 300_000, 5).px == 700_000
    assert delta_from_kalshi(1, "yes", 300_000, 5).side is BookSide.BID
    with pytest.raises(ValueError):
        delta_from_kalshi(1, "maybe", 1, 1)


def test_polymarket_profile() -> None:
    p = PolymarketProfile("0.05", fee_exponent=2, taker_only=False, min_notional=5_000_000)
    spec = MarketSpec("p", p, 0, 1, uniform_grid(1_000), 1, 500)
    fees = spec.fee_model()
    assert isinstance(fees, PolymarketFees) and fees.rate == "0.05"
    assert fees.exponent == 2 and not fees.taker_only and fees.enabled
    assert p.position_mode is PositionMode.TOKENS
    assert p.size_ok(spec, 1) and p.price_ok(spec.grid, 1_000)
    assert p.default_grid().contains(10_000)


def test_hip4_profile() -> None:
    h = HIP4Profile(taker_rate="0.0006", referral_discount="0.04")
    spec = MarketSpec("h", h, 0, 1, h.default_grid(), 100, 100)
    assert isinstance(spec.fee_model(), HIP4Fees)
    assert h.size_ok(spec, 300) and not h.size_ok(spec, 150)
    assert h.price_ok(spec.grid, 123_450) and not h.price_ok(spec.grid, 123_455)
    assert not h.price_ok(spec.grid, 999_500)


def test_hip4_interpolated_settlement() -> None:
    # marks 100 at t=0 and 110 at t=10; at t=5 the mark is 105
    assert btc_binary_settles_yes(100, 0, 110, 10, 5, 105)
    assert not btc_binary_settles_yes(100, 0, 110, 10, 5, 106)
    with pytest.raises(ValueError):
        btc_binary_settles_yes(100, 10, 110, 10, 10, 1)


def test_spec_validation_and_fee_override() -> None:
    custom = CustomFees(lambda f: 1)
    spec = MarketSpec("c", KalshiProfile(), 0, 1, uniform_grid(10_000), 1, 1, fees=custom)
    assert spec.fee_model() is custom
    with pytest.raises(ValueError):
        MarketSpec("c", KalshiProfile(), 2, 1, uniform_grid(10_000), 1, 1)
    with pytest.raises(ValueError):
        MarketSpec("c", KalshiProfile(), 0, 1, uniform_grid(10_000), 0, 1)
