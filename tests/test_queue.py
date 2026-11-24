"""M3 maker fixtures: queue position, cancel models, cancel races, fills through."""

import pytest

from predictsim.events import Side
from predictsim.orders import OrderStatus, OrderType, Outcome
from predictsim.queue import QueueModel, after_cancels, on_level_change, on_trade
from predictsim.venues import PolymarketProfile
from tests.helpers import BookSide, Delta, Snapshot, Trade, make

BOOK = Snapshot(1, ((400_000, 1000),), ((420_000, 500),))


def resting_bid(queue: QueueModel = QueueModel.PESSIMISTIC):  # type: ignore[no-untyped-def]
    ex, fills = make(PolymarketProfile("0.05"), queue=queue)
    ex.on_event(BOOK, 0)
    o = ex.new_order(1, Outcome.YES, Side.BUY, 400_000, 500, OrderType.GTC)
    ex.arrive(o, 1)
    return ex, fills, o


def test_maker_fills_after_queue_drains() -> None:
    ex, fills, o = resting_bid()
    assert o.status is OrderStatus.LIVE and o.queue_ahead == 1000
    ex.on_event(Trade(2, 400_000, 600, Side.SELL), 1)
    assert o.queue_ahead == 400 and not fills
    ex.on_event(Delta(3, BookSide.BID, 400_000, 400), 2)  # explained by the trade
    assert o.queue_ahead == 400
    ex.on_event(Trade(4, 400_000, 500, Side.SELL), 3)
    assert o.queue_ahead == 0 and [(f.size, f.is_maker, f.fee) for f in fills] == [(100, True, 0)]
    ex.on_event(Trade(5, 400_000, 1000, Side.SELL), 4)
    assert o.status is OrderStatus.FILLED and sum(f.size for f in fills) == 500
    assert ex.account.cash == 100_000_000 - 2_000_000 and ex.account.reserved == 0


def test_buy_aggressor_does_not_hit_bids() -> None:
    ex, fills, o = resting_bid()
    ex.on_event(Trade(2, 400_000, 5000, Side.BUY), 1)
    assert o.queue_ahead == 1000 and not fills


@pytest.mark.parametrize(
    ("model", "expected"),
    [(QueueModel.PESSIMISTIC, 1000), (QueueModel.PROPORTIONAL, 800), (QueueModel.OPTIMISTIC, 600)],
)
def test_cancel_models(model: QueueModel, expected: int) -> None:
    ex, _, o = resting_bid(model)
    # 400 centis leave the level without trading: 1000 -> 1600 then 1600 -> 1200
    ex.on_event(Delta(2, BookSide.BID, 400_000, 1600), 1)
    ex.on_event(Delta(3, BookSide.BID, 400_000, 1200), 2)
    proportional = 1000 - (400 * 1000) // 1600
    assert o.queue_ahead == (proportional if model is QueueModel.PROPORTIONAL else expected)


def test_queue_never_exceeds_level() -> None:
    ex, _, o = resting_bid()
    ex.on_event(Delta(2, BookSide.BID, 400_000, 300), 1)
    assert o.queue_ahead == 300
    ex.on_event(Snapshot(3, ((400_000, 100),), ((420_000, 500),)), 2)
    assert o.queue_ahead == 100


def test_fills_in_full_when_opposite_moves_through() -> None:
    ex, fills, o = resting_bid()
    ex.on_event(Delta(2, BookSide.BID, 400_000, 0), 1)
    assert not fills
    ex.on_event(Delta(3, BookSide.ASK, 390_000, 50), 2)  # ask at 0.39 <= our 0.40 bid
    assert o.status is OrderStatus.FILLED
    assert [(f.px, f.size, f.is_maker) for f in fills] == [(400_000, 500, True)]


def test_resting_ask_fills_through_on_snapshot() -> None:
    ex, fills = make(PolymarketProfile("0.05"))
    ex.on_event(BOOK, 0)
    ex.account.split(500)
    o = ex.new_order(1, Outcome.YES, Side.SELL, 420_000, 500, OrderType.GTC)
    ex.arrive(o, 1)
    assert o.status is OrderStatus.LIVE
    ex.on_event(Snapshot(2, ((430_000, 10),), ((440_000, 10),)), 1)
    assert o.status is OrderStatus.FILLED and fills[0].px == 420_000


def test_pure_functions() -> None:
    assert after_cancels(QueueModel.OPTIMISTIC, 0, 10, 5) == 0
    assert after_cancels(QueueModel.PROPORTIONAL, 5, 0, 5) == 0
    assert on_level_change(QueueModel.OPTIMISTIC, 10, 20, 25, 0) == 10
    assert on_level_change(QueueModel.OPTIMISTIC, 10, 20, 12, 5) == 7
    assert on_trade(10, 4) == (6, 0) and on_trade(10, 15) == (0, 5)
