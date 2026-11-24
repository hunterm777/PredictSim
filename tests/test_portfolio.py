"""Portfolio mode: one shared cash balance, one global time order."""

from __future__ import annotations

import pytest

from predictsim import (
    BacktestConfig,
    Context,
    Event,
    Fixed,
    LatencyConfig,
    LogNormal,
    OrderBook,
    OrderStatus,
    Outcome,
    Settle,
    Side,
    Snapshot,
    Strategy,
    Trade,
    run_backtest,
    run_portfolio,
)
from predictsim.portfolio import market_seed
from tests.sweep_helpers import BuyAtOrBelow, kalshi_spec, market_events

CASH = 100_000_000


def test_one_market_portfolio_matches_run_backtest() -> None:
    cfg = BacktestConfig(CASH)
    single = run_backtest(BuyAtOrBelow(400_000), market_events(), kalshi_spec("a"), cfg)
    port = run_portfolio(BuyAtOrBelow(400_000), [(market_events(), kalshi_spec("a"))], cfg)
    assert port.markets[0].fills == single.fills
    assert port.net_pnl == single.net_pnl == 600_000
    assert port.summary() == single.summary()
    assert port.final_cash == single.final_cash
    assert port.markets[0].initial_cash == 0 and port.markets[0].final_equity == single.net_pnl
    assert port.round_trips == single.round_trips and port.trade_stats().n_trades == 1


def test_cash_is_shared_and_payouts_fund_later_orders() -> None:
    # $0.42 covers one 1-contract bid at 0.40 plus its taker-fee bound ($0.02)
    cfg = BacktestConfig(420_000)
    markets = [(market_events(0), kalshi_spec("a")), (market_events(0), kalshi_spec("b"))]
    port = run_portfolio(BuyAtOrBelow(400_000), markets, cfg)
    a, b = port.markets
    assert len(a.fills) == 1
    rejected = [o for o in b.orders if o.status is OrderStatus.REJECTED]
    assert rejected and "available" in rejected[0].reason
    # a settles YES at t=900 and pays $1: b's market is closed by then, so b never trades
    assert not b.fills
    assert port.final_cash == 420_000 - 400_000 + 1_000_000
    assert port.final_cash == port.initial_cash + sum(r.final_cash for r in port.markets)
    assert port.min_cash == 20_000


def test_later_market_trades_on_earlier_payout() -> None:
    cfg = BacktestConfig(420_000)
    markets = [(market_events(0), kalshi_spec("a")), (market_events(1_000), kalshi_spec("b", 1_000, 2_000))]
    port = run_portfolio(lambda spec: BuyAtOrBelow(400_000), markets, cfg)
    assert [len(r.fills) for r in port.markets] == [1, 1]
    assert port.net_pnl == 1_200_000
    assert port.equity[0] == (0, 420_000) and port.final_equity == 1_620_000


class Recorder(Strategy):
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    def on_start(self, ctx: Context) -> None:
        self.calls.append((ctx.now, ctx.market_id, "start"))

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        self.calls.append((ctx.now, ctx.market_id, "book"))

    def on_trade(self, ctx: Context, trade: Trade) -> None:
        self.calls.append((ctx.now, ctx.market_id, "trade"))

    def on_end(self, ctx: Context) -> None:
        self.calls.append((ctx.now, ctx.market_id, "end"))


def test_events_run_in_one_global_time_order() -> None:
    rec = Recorder()
    markets = [
        (market_events(500), kalshi_spec("late", 500, 1_500)),
        (market_events(0), kalshi_spec("early")),
    ]
    run_portfolio(rec, markets, BacktestConfig(CASH))
    times = [t for t, _, _ in rec.calls]
    assert times == sorted(times)
    assert rec.calls[0] == (0, "early", "start")
    assert (500, "late", "start") in rec.calls
    assert rec.calls.index((500, "late", "start")) > rec.calls.index((200, "early", "trade"))


def test_same_timestamp_ties_go_to_the_first_market() -> None:
    rec = Recorder()
    markets = [(market_events(), kalshi_spec("x")), (market_events(), kalshi_spec("y"))]
    run_portfolio(rec, markets, BacktestConfig(CASH))
    books = [m for _, m, kind in rec.calls if kind == "book"]
    assert books[:2] == ["x", "y"]


class CrossSubmit(Strategy):
    """Keep market b's context and send its order from market a's callback."""

    def __init__(self) -> None:
        self.ctxs: dict[str, Context] = {}
        self.sent = False

    def on_start(self, ctx: Context) -> None:
        self.ctxs[ctx.market_id] = ctx

    def on_trade(self, ctx: Context, trade: Trade) -> None:
        if ctx.market_id == "a" and not self.sent:
            self.sent = True
            self.ctxs["b"].submit(Side.BUY, 100, 420_000)
            self.ctxs["b"].submit(Side.BUY, 100, 420_000)  # b's next work is already the first


def test_order_sent_to_another_market_arrives_on_time() -> None:
    a = [Snapshot(10, ((400_000, 100),), ((420_000, 100),)), Trade(20, 400_000, 10, Side.SELL)]
    b: list[Event] = [Snapshot(10, ((400_000, 100),), ((420_000, 1_000),)), Snapshot(500, (), ())]
    cfg = BacktestConfig(CASH, LatencyConfig(submit=Fixed(50)))
    port = run_portfolio(CrossSubmit(), [(a, kalshi_spec("a")), (b, kalshi_spec("b"))], cfg)
    fills = port.markets[1].fills
    assert [(f.ts, f.px) for f in fills] == [(70, 420_000), (70, 420_000)]


class CrossCancel(Strategy):
    """Rest a bid in market b, then cancel it from market a's callback."""

    def __init__(self) -> None:
        self.ctxs: dict[str, Context] = {}

    def on_start(self, ctx: Context) -> None:
        self.ctxs[ctx.market_id] = ctx

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        if ctx.market_id == "b" and ctx.now == 10:
            ctx.submit(Side.BUY, 100, 390_000)

    def on_trade(self, ctx: Context, trade: Trade) -> None:
        if ctx.market_id == "a":
            self.ctxs["b"].cancel_all()


def test_cancel_sent_from_another_market_uses_the_global_clock() -> None:
    a = [Snapshot(10, ((400_000, 100),), ((420_000, 100),)), Trade(40, 400_000, 10, Side.SELL)]
    b: list[Event] = [Snapshot(10, ((400_000, 100),), ((420_000, 100),)), Snapshot(500, (), ())]
    cfg = BacktestConfig(CASH, LatencyConfig(cancel=Fixed(30)))
    port = run_portfolio(CrossCancel(), [(a, kalshi_spec("a")), (b, kalshi_spec("b"))], cfg)
    (order,) = port.markets[1].orders
    assert (order.status, order.done_ts) == (OrderStatus.CANCELLED, 70)


class TimerAfterData(Strategy):
    """A timer that fires after the market's last event but before close."""

    def __init__(self) -> None:
        self.fired: list[int] = []

    def on_start(self, ctx: Context) -> None:
        ctx.set_timer(600)

    def on_timer(self, ctx: Context) -> None:
        self.fired.append(ctx.now)


def test_actions_after_the_last_event_still_run_in_order() -> None:
    strat = TimerAfterData()
    events: list[Event] = [Snapshot(10, ((400_000, 100),), ((420_000, 100),))]
    port = run_portfolio(
        strat, [(events, kalshi_spec("a")), (market_events(), kalshi_spec("b"))], BacktestConfig(CASH)
    )
    assert strat.fired == [600, 600]
    assert port.markets[0].equity[-1][0] == 1_000


def test_portfolio_is_deterministic_and_seeds_markets_apart() -> None:
    cfg = BacktestConfig(CASH, LatencyConfig(submit=LogNormal(30, 0.5), data=LogNormal(10, 0.5)), seed=7)

    def run() -> list[object]:
        markets = [(market_events(), kalshi_spec(m)) for m in ("a", "b", "c")]
        port = run_portfolio(lambda spec: BuyAtOrBelow(400_000), markets, cfg)
        return [r.fills for r in port.markets] + [port.equity]

    assert run() == run()
    assert market_seed(7, 0) != market_seed(7, 1) and market_seed(7, 0) == market_seed(7, 0)


def test_duplicate_market_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="unique"):
        run_portfolio(Strategy(), [(market_events(), kalshi_spec("a"))] * 2, BacktestConfig(CASH))


def test_portfolio_summary_uses_the_shared_account() -> None:
    markets = [(market_events(0, settle=0), kalshi_spec("lose")), (market_events(0), kalshi_spec("win"))]
    port = run_portfolio(BuyAtOrBelow(400_000), markets, BacktestConfig(1_000_000))
    s = port.summary()
    assert s.net_pnl == 200_000 and s.win_rate == 0.5  # -0.40 + 0.60
    assert s.return_on_capital == 0.25  # $0.80 out of the account at most
    assert port.min_cash == 200_000
    assert set(port.breakdown()) == {"lose", "win"}
    assert port.total_fees == 0
    assert port.performance(100).n_periods == 10  # t = 0 to 1000
    assert Settle(0, 0).settle_fraction == 0 and Outcome.YES in Outcome
