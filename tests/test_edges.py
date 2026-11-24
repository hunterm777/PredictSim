"""Edge cases of order validation, the shadow book and result chaining."""

import pytest

from predictsim.backtest import BacktestConfig, Engine, run_backtest
from predictsim.events import Settle, Side
from predictsim.metrics import BacktestResult, ManyResult
from predictsim.orders import Order, OrderStatus, OrderType, Outcome
from predictsim.spec import MarketSpec, uniform_grid
from predictsim.strategy import Context, Strategy
from predictsim.venues import KalshiProfile
from tests.helpers import BookSide, Delta, Snapshot, make

BOOK = Snapshot(0, ((400_000, 1000),), ((420_000, 1000), (430_000, 1000)))


def test_settle_fraction_must_be_in_range() -> None:
    with pytest.raises(ValueError):
        Settle(0, 1_000_001)


def test_limit_order_needs_a_price() -> None:
    ex, _ = make()
    with pytest.raises(ValueError):
        ex.new_order(0, Outcome.YES, Side.BUY, None, 100, OrderType.GTC)


def test_size_and_value_validation() -> None:
    spec = MarketSpec("m", KalshiProfile(), 0, 100, uniform_grid(1), 1, 50)
    ex, _ = make()
    ex.spec, ex.grid = spec, spec.grid
    small = ex.new_order(0, Outcome.YES, Side.BUY, 400_000, 10, OrderType.GTC)
    assert small.status is OrderStatus.REJECTED and "below the minimum 50" in small.reason
    odd = ex.new_order(0, Outcome.YES, Side.BUY, 1, 99, OrderType.GTC)  # $0.0000099
    assert odd.status is OrderStatus.REJECTED and "whole micro-dollar" in odd.reason


def test_cancel_one_of_two_resting_orders_keeps_the_level() -> None:
    ex, _ = make()
    ex.on_event(BOOK, 0)
    a = ex.new_order(0, Outcome.YES, Side.BUY, 390_000, 100, OrderType.GTC)
    b = ex.new_order(0, Outcome.YES, Side.BUY, 390_000, 100, OrderType.GTC)
    ex.arrive(a, 0)
    ex.arrive(b, 0)
    assert ex.cancel(a, 1)
    assert ex.resting[(BookSide.BID, 390_000)] == [b]


def test_taken_level_is_skipped_by_the_next_taker() -> None:
    ex, fills = make()
    ex.on_event(BOOK, 0)
    ex.arrive(ex.new_order(0, Outcome.YES, Side.BUY, 420_000, 1000, OrderType.IOC), 0)
    ex.arrive(ex.new_order(0, Outcome.YES, Side.BUY, 430_000, 500, OrderType.IOC), 0)
    assert [(f.px, f.size) for f in fills] == [(420_000, 1000), (430_000, 500)]


def test_second_settlement_is_ignored() -> None:
    ex, _ = make()
    ex.on_event(Settle(5, 1_000_000), 0)
    ex.on_event(Settle(6, 0), 1)
    assert ex.settlement == (5, 0, 0)


def test_skipped_book_events_in_lenient_mode() -> None:
    ex, _ = make()
    ex.book.strict = False
    ex.on_event(BOOK, 0)
    assert not ex.on_event(Delta(1, BookSide.BID, 425_000, 10), 1)  # crosses the ask
    assert not ex.on_event(Snapshot(2, ((500_000, 1),), ((400_000, 1),)), 2)  # crossed


def test_empty_equity_curve_is_skipped_when_chaining() -> None:
    empty = BacktestResult("a", 100, 100, [], [], [], 100, None)
    full = BacktestResult("b", 100, 150, [], [], [(0, 100), (1, 150)], 100, None)
    assert ManyResult([empty, full]).summary().max_drawdown == 0


def test_order_keeps_an_explicit_remaining() -> None:
    o = Order(1, 0, Outcome.YES, Side.BUY, 400_000, 500, OrderType.GTC, BookSide.BID, 400_000, 200)
    assert o.remaining == 200


def test_context_book_is_the_strategy_view() -> None:
    seen: list[int | None] = []

    class Look(Strategy):
        def on_book(self, ctx: Context, book: object) -> None:
            seen.append(ctx.book.best_bid())

    spec = MarketSpec("m", KalshiProfile(), 0, 10, uniform_grid(10_000), 1, 1)
    run_backtest(Look(), [BOOK], spec, BacktestConfig(1_000_000))
    assert seen == [400_000]


def test_equity_before_any_two_sided_book_is_cash() -> None:
    spec = MarketSpec("m", KalshiProfile(), 0, 10, uniform_grid(10_000), 1, 1)
    engine = Engine(Strategy(), [Snapshot(0, ((400_000, 10),), ())], spec, BacktestConfig(5_000_000))
    engine.start()
    engine.step()
    assert engine.mark_equity() == 5_000_000
