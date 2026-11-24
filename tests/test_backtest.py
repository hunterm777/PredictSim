"""M4: the event loop, latency races, timers, run_many and metrics."""

from predictsim import (
    BacktestConfig,
    Context,
    Fixed,
    LatencyConfig,
    OrderBook,
    OrderStatus,
    OrderType,
    Outcome,
    Settle,
    Side,
    Strategy,
    Trade,
    run_backtest,
    run_many,
)
from predictsim.events import BookSide, Delta, Snapshot
from predictsim.fees.base import FeeInput
from predictsim.metrics import max_drawdown
from predictsim.orders import Fill
from predictsim.venues import KalshiProfile, PolymarketProfile
from tests.helpers import spec_for

BOOK = Snapshot(10, ((400_000, 1000),), ((420_000, 1000),))


class RestThenCancel(Strategy):
    """Rest a bid at 0.40 on the first book; request a cancel at t=50."""

    def __init__(self) -> None:
        self.sent = False
        self.fills: list[Fill] = []

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        if not self.sent:
            self.sent = True
            ctx.submit(Side.BUY, 500, 400_000)
            ctx.set_timer(40)

    def on_timer(self, ctx: Context) -> None:
        ctx.cancel_all()

    def on_fill(self, ctx: Context, fill: Fill) -> None:
        self.fills.append(fill)


def events(trade_ts: int) -> list:  # type: ignore[type-arg]
    return [BOOK, Trade(trade_ts, 400_000, 1500, Side.SELL), Settle(200, 1_000_000)]


def config(cancel_ns: int) -> BacktestConfig:
    return BacktestConfig(100_000_000, LatencyConfig(cancel=Fixed(cancel_ns)))


def test_cancel_loses_race_to_fill() -> None:
    strat = RestThenCancel()
    res = run_backtest(strat, events(60), spec_for(KalshiProfile()), config(30))
    # cancel sent at t=50 arrives at t=80; the trade at t=60 fills first
    assert [(f.ts, f.size) for f in strat.fills] == [(60, 500)]
    assert res.orders[0].status is OrderStatus.FILLED
    assert res.final_cash == 100_000_000 - 2_000_000 + 5_000_000


def test_cancel_wins_race_when_it_arrives_first() -> None:
    strat = RestThenCancel()
    res = run_backtest(strat, events(90), spec_for(KalshiProfile()), config(30))
    assert not strat.fills and res.orders[0].status is OrderStatus.CANCELLED
    assert res.orders[0].done_ts == 80 and res.final_cash == 100_000_000


def test_submit_latency_and_lagged_data() -> None:
    seen: list[tuple[int, int | None]] = []

    class Watch(Strategy):
        def on_book(self, ctx: Context, book: OrderBook) -> None:
            seen.append((ctx.now, book.best_bid()))
            if len(seen) == 1:
                ctx.submit(Side.BUY, 100, 420_000, order_type=OrderType.IOC)

        def on_trade(self, ctx: Context, trade: Trade) -> None:
            seen.append((ctx.now, -1))

    evs = [
        BOOK,
        Delta(20, BookSide.ASK, 420_000, 0),
        Trade(25, 400_000, 1, Side.SELL),
        Delta(30, BookSide.ASK, 430_000, 50),
    ]
    cfg = BacktestConfig(100_000_000, LatencyConfig(submit=Fixed(15), data=Fixed(5)))
    res = run_backtest(Watch(), evs, spec_for(KalshiProfile()), cfg)
    assert seen == [(15, 400_000), (25, 400_000), (30, -1), (35, 400_000)]
    # submitted at 15, live at 30: the 0.42 ask left at t=20, so nothing to take
    order = res.orders[0]
    assert order.live_ts is None and order.status is OrderStatus.CANCELLED and not res.fills


def test_close_cancels_and_late_events_still_replay() -> None:
    class Late(Strategy):
        def on_book(self, ctx: Context, book: OrderBook) -> None:
            if not ctx.open_orders and ctx.now < 100:
                ctx.submit(Side.BUY, 100, 390_000)

        def on_end(self, ctx: Context) -> None:
            assert ctx.submit(Side.BUY, 100, 390_000).status is OrderStatus.REJECTED

    spec = spec_for(KalshiProfile(), close_ts=50)
    evs = [BOOK, Delta(60, BookSide.BID, 410_000, 5)]
    res = run_backtest(Late(), evs, spec, BacktestConfig(10_000_000))
    assert res.orders[0].reason == "market closed" and res.orders[0].done_ts == 50
    assert res.summary().n_fills == 0


def test_context_views_and_tokens_ops() -> None:
    out: dict[str, object] = {}

    class Peek(Strategy):
        def on_start(self, ctx: Context) -> None:
            ctx.split(200)
            ctx.merge(100)
            ctx.set_timer(10**9)  # fires after close: dropped

        def on_book(self, ctx: Context, book: OrderBook) -> None:
            o = ctx.submit(Side.SELL, 100, 420_000, outcome=Outcome.YES)
            out.update(cash=ctx.cash, avail=ctx.available_cash, pos=ctx.positions, n=len(ctx.open_orders))
            ctx.cancel(o.order_id)
            ctx.cancel(999)

    spec = spec_for(PolymarketProfile("0.05"))
    run_backtest(Peek(), [BOOK], spec, BacktestConfig(10_000_000))
    assert out == {
        "cash": 9_000_000,
        "avail": 9_000_000 - 12_180,
        "pos": {Outcome.YES: 100, Outcome.NO: 100},
        "n": 1,
    }


def test_time_must_not_go_backwards() -> None:
    import pytest

    with pytest.raises(ValueError, match="event 1"):
        run_backtest(
            Strategy(),
            [BOOK, Delta(5, BookSide.BID, 410_000, 1)],
            spec_for(KalshiProfile()),
            BacktestConfig(1),
        )


def test_negative_timer_rejected() -> None:
    import pytest

    class Bad(Strategy):
        def on_start(self, ctx: Context) -> None:
            ctx.set_timer(-1)

    with pytest.raises(ValueError):
        run_backtest(Bad(), [BOOK], spec_for(KalshiProfile()), BacktestConfig(1))


class BuyOnce(Strategy):
    def on_start(self, ctx: Context) -> None:
        self.done = False

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        if not self.done:
            self.done = True
            ctx.submit(Side.BUY, 1000, 420_000, order_type=OrderType.IOC)


def test_run_many_carries_or_resets_cash() -> None:
    win = [BOOK, Settle(100, 1_000_000)]
    lose = [BOOK, Settle(100, 0)]
    spec = spec_for(KalshiProfile())
    carry = run_many(BuyOnce(), [(win, spec), (lose, spec)], BacktestConfig(10_000_000))
    first, second = carry.results
    # 10 @ 0.42: cost 4.20, fee 0.17052 + rounding = 0.18
    assert first.final_cash == 10_000_000 - 4_200_000 - 180_000 + 10_000_000
    assert second.initial_cash == first.final_cash
    reset = run_many(BuyOnce(), [(win, spec), (lose, spec)], BacktestConfig(10_000_000), carry_cash=False)
    assert reset.results[1].initial_cash == 10_000_000
    summary = carry.summary()
    assert summary.n_fills == 2 and summary.win_rate == 0.5 and summary.total_fees == 360_000
    assert summary.net_pnl == first.net_pnl + second.net_pnl
    assert summary.gross_pnl == summary.net_pnl + 360_000
    assert set(carry.breakdown()) == {"m"}
    assert summary.max_drawdown == 4_380_000 + 0  # second market loses its whole stake


def test_max_drawdown() -> None:
    assert max_drawdown([]) == 0
    assert max_drawdown([(0, 10), (1, 15), (2, 5), (3, 20), (4, 12)]) == 10


def test_fee_input_is_documented() -> None:
    assert FeeInput(1, 2, 3, True, False, 0).is_maker
