"""Sharpe, Sortino, period returns, round trips and trade statistics."""

from __future__ import annotations

import math

import numpy as np
import pytest

from predictsim import (
    BacktestConfig,
    Context,
    Event,
    KalshiProfile,
    OrderBook,
    Outcome,
    Settle,
    Side,
    Snapshot,
    Strategy,
    Trade,
    run_backtest,
    run_many,
)
from predictsim.stats import performance, period_returns, sharpe, sortino, trade_stats
from predictsim.trades import RoundTrip
from tests.sweep_helpers import BuyAtOrBelow, kalshi_spec, market_events

R = np.array([0.10, -0.05, 0.02, -0.01])


def test_period_returns_sample_the_last_point_in_each_period() -> None:
    curve = [(0, 100), (5, 120), (10, 110), (25, 121), (26, 99)]
    r = period_returns(curve, 10)
    # samples at t = 0, 10, 20, 30: 100, 110, 110, 99
    assert np.allclose(r, [0.10, 0.0, -0.10])
    assert np.allclose(period_returns(curve, 10, start=-10), [0.0, 0.10, 0.0, -0.10])
    assert len(period_returns([(0, 5)], 10)) == 0
    assert len(period_returns([], 10)) == 0


def test_period_returns_input_checks() -> None:
    with pytest.raises(ValueError, match="positive"):
        period_returns([(0, 1)], 0)
    with pytest.raises(ValueError, match="positive equity"):
        period_returns([(0, 0), (10, 5)], 10)


def test_sharpe_and_sortino_match_their_definitions() -> None:
    mean, sd = R.mean(), R.std(ddof=1)
    assert sharpe(R) == pytest.approx(mean / sd)
    assert sharpe(R, risk_free=0.01) == pytest.approx((mean - 0.01) / sd)
    assert sharpe(R, periods_per_year=252) == pytest.approx(mean / sd * math.sqrt(252))
    downside = math.sqrt((0.05**2 + 0.01**2) / 4)
    assert sortino(R) == pytest.approx(mean / downside)
    assert sortino(R, periods_per_year=12) == pytest.approx(mean / downside * math.sqrt(12))
    dd_t = math.sqrt(((0.10 - 0.02) ** 2 * 0 + 0.07**2 + 0.0 + 0.03**2) / 4)
    assert sortino(R, target=0.02) == pytest.approx((mean - 0.02) / dd_t)


def test_undefined_ratios_are_none() -> None:
    assert sharpe(np.array([0.1])) is None and sortino(np.array([0.1])) is None
    assert sharpe(np.array([0.1, 0.1])) is None
    assert sortino(np.array([0.1, 0.2])) is None
    perf = performance([(0, 100)], 10)
    assert (perf.n_periods, perf.mean_return, perf.volatility, perf.sharpe) == (0, None, None, None)


def trip(pnl: int, fees: int = 0, entry: int = 0, exit: int = 10) -> RoundTrip:
    return RoundTrip("m", entry, exit, 2, 200, fees, pnl, "flat")


def test_trade_stats() -> None:
    stats = trade_stats([trip(300, 10), trip(-100, 10, 0, 30), trip(100), trip(0)])
    assert (stats.n_trades, stats.n_wins, stats.n_losses) == (4, 2, 1)
    assert stats.win_rate == 0.5 and stats.total_pnl == 300 and stats.total_fees == 20
    assert stats.expectancy == 75 and stats.avg_win == 200 and stats.avg_loss == -100
    assert stats.profit_factor == 4.0 and stats.avg_hold_ns == 15
    empty = trade_stats([])
    assert empty.win_rate is None and empty.expectancy is None and empty.profit_factor is None
    assert trade_stats([trip(5)]).profit_factor is None and trip(5, 2).gross_pnl == 7


class FlipKalshi(Strategy):
    """Buy 2 YES, then sell 4 YES (net short 2, never flat), then buy 2."""

    def __init__(self) -> None:
        self.step = 0

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        if ctx.open_orders:
            return
        plan = [(Side.BUY, 200, 420_000), (Side.SELL, 400, 400_000), (Side.BUY, 200, 420_000)]
        if self.step < len(plan):
            side, size, px = plan[self.step]
            self.step += 1
            ctx.submit(side, size, px)


def flip_events(end: Event) -> list[Event]:
    snap = Snapshot(10, ((400_000, 10_000),), ((420_000, 10_000),))
    return [snap, Snapshot(20, snap.bids, snap.asks), Snapshot(30, snap.bids, snap.asks), end]


def test_round_trip_through_a_flip_and_back_to_flat() -> None:
    res = run_backtest(FlipKalshi(), flip_events(Settle(900, 0)), kalshi_spec("k"), BacktestConfig(10**8))
    (rt,) = res.round_trips
    assert (rt.entry_ts, rt.exit_ts, rt.n_fills, rt.volume, rt.exit) == (10, 30, 3, 800, "flat")
    assert rt.pnl == res.net_pnl and rt.fees == res.total_fees


def test_round_trip_settled_and_open() -> None:
    settled = run_backtest(BuyAtOrBelow(400_000), market_events(), kalshi_spec("s"), BacktestConfig(10**8))
    assert [(t.exit, t.pnl, t.exit_ts) for t in settled.round_trips] == [("settled", 600_000, 900)]
    events = [*market_events()[:-1], Trade(950, 410_000, 1, Side.BUY)]
    held = run_backtest(BuyAtOrBelow(400_000), events, kalshi_spec("o"), BacktestConfig(10**8))
    (rt,) = held.round_trips
    assert rt.exit == "open" and rt.pnl == held.net_pnl == 5_000  # marked at mid (0.39 + 0.42) / 2
    assert held.trade_stats().n_trades == 1 and held.performance(100).n_periods == 10


def test_many_result_equity_and_stats() -> None:
    mk = [(market_events(i * 1_000), kalshi_spec(f"m{i}", i * 1_000, i * 1_000 + 1_000)) for i in range(2)]
    many = run_many(BuyAtOrBelow(400_000), mk, BacktestConfig(10**8))
    assert many.equity[0] == (0, 10**8) and many.equity[-1][1] == 10**8 + 1_200_000
    assert many.trade_stats().n_wins == 2 and len(many.round_trips) == 2
    assert many.performance(500).sharpe is not None
    assert run_many(Strategy(), [], BacktestConfig(1)).equity == []
    assert KalshiProfile().name == "kalshi" and Outcome.NO.value == "no"
