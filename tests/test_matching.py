"""M3 hand-worked taker fixtures, to the micro-dollar."""

from predictsim.events import Side
from predictsim.orders import OrderStatus, OrderType, Outcome
from predictsim.venues import PolymarketProfile
from tests.helpers import BookSide, Delta, Snapshot, make

BOOK = Snapshot(1, ((400_000, 1000), (390_000, 500)), ((420_000, 500), (430_000, 1000)))


def test_taker_sweep_walks_levels_with_kalshi_fees() -> None:
    ex, fills = make()
    ex.on_event(BOOK, 0)
    o = ex.new_order(1, Outcome.YES, Side.BUY, 430_000, 800, OrderType.GTC)
    ex.arrive(o, 1)
    assert [(f.px, f.size, f.is_maker) for f in fills] == [(420_000, 500, False), (430_000, 300, False)]
    # 5 @ 0.42: fee 0.085260 + rounding 0.004740 = $0.09
    # 3 @ 0.43: fee 0.051471 + rounding 0.008529 - rebate 0.01 = $0.05
    assert [f.fee for f in fills] == [90_000, 50_000]
    assert ex.account.cash == 100_000_000 - 2_100_000 - 1_290_000 - 140_000
    assert o.status is OrderStatus.FILLED and ex.account.reserved == 0


def test_taken_size_is_not_available_twice_until_level_updates() -> None:
    ex, fills = make()
    ex.on_event(BOOK, 0)
    a = ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 400, OrderType.IOC)
    ex.arrive(a, 1)
    b = ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 400, OrderType.IOC)
    ex.arrive(b, 1)
    assert a.filled == 400 and b.filled == 100 and b.status is OrderStatus.CANCELLED
    ex.on_event(Delta(2, BookSide.ASK, 420_000, 500), 1)  # level refreshed
    c = ex.new_order(2, Outcome.YES, Side.BUY, 420_000, 400, OrderType.IOC)
    ex.arrive(c, 2)
    assert c.filled == 400 and len(fills) == 3


def test_snapshot_clears_shadow() -> None:
    ex, _ = make()
    ex.on_event(BOOK, 0)
    ex.arrive(ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 500, OrderType.IOC), 1)
    ex.on_event(BOOK, 1)
    again = ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 500, OrderType.IOC)
    ex.arrive(again, 2)
    assert again.filled == 500


def test_buy_no_takes_yes_bids() -> None:
    ex, fills = make(PolymarketProfile())
    ex.on_event(BOOK, 0)
    o = ex.new_order(1, Outcome.NO, Side.BUY, 610_000, 1200, OrderType.IOC)
    assert (o.yes_side, o.yes_px) == (BookSide.ASK, 390_000)
    ex.arrive(o, 1)
    assert [(f.outcome, f.px, f.size) for f in fills] == [
        (Outcome.NO, 600_000, 1000),
        (Outcome.NO, 610_000, 200),
    ]
    # Polymarket sports 0.05: 10 x 0.05 x 0.6 x 0.4 = 0.12; 2 x 0.05 x 0.61 x 0.39 = 0.02379
    assert [f.fee for f in fills] == [120_000, 23_790]
    assert ex.account.holdings[Outcome.NO] == 1200


def test_fok_ioc_post_only_and_market() -> None:
    ex, fills = make()
    ex.on_event(BOOK, 0)
    fok = ex.new_order(1, Outcome.YES, Side.BUY, 430_000, 2000, OrderType.FOK)
    ex.arrive(fok, 1)
    assert fok.status is OrderStatus.CANCELLED and not fills
    post = ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 100, OrderType.POST_ONLY)
    ex.arrive(post, 1)
    assert post.status is OrderStatus.REJECTED
    resting = ex.new_order(1, Outcome.YES, Side.BUY, 410_000, 100, OrderType.POST_ONLY)
    ex.arrive(resting, 1)
    assert resting.status is OrderStatus.LIVE
    mkt = ex.new_order(1, Outcome.YES, Side.SELL, None, 1600, OrderType.MARKET)
    assert mkt.px == 10_000
    ex.arrive(mkt, 1)
    assert mkt.filled == 1500 and mkt.status is OrderStatus.CANCELLED
    full = ex.new_order(1, Outcome.YES, Side.BUY, 430_000, 1500, OrderType.FOK)
    ex.arrive(full, 1)
    assert full.status is OrderStatus.FILLED


def test_validation_rejections() -> None:
    ex, _ = make(cash=1_000_000)
    ex.on_event(BOOK, 0)
    cases = [
        (Outcome.YES, Side.BUY, 405_000, 100, "off the grid"),
        (Outcome.YES, Side.BUY, 400_000, 0, "size step"),
        (Outcome.YES, Side.BUY, 400_000, 1_000, "needs"),
    ]
    for outcome, side, px, size, reason in cases:
        o = ex.new_order(1, outcome, side, px, size, OrderType.GTC)
        assert o.status is OrderStatus.REJECTED and reason in o.reason
    early = ex.new_order(-1, Outcome.YES, Side.BUY, 400_000, 100, OrderType.GTC)
    assert early.reason == "market not open"
    ex.close(5)
    late = ex.new_order(6, Outcome.YES, Side.BUY, 400_000, 100, OrderType.GTC)
    assert late.reason == "market closed"


def test_order_ids_are_sequential() -> None:
    ex, _ = make()
    ids = [ex.new_order(1, Outcome.YES, Side.BUY, 400_000, 100, OrderType.GTC).order_id for _ in range(3)]
    assert ids == [1, 2, 3]


def test_cancel_and_close() -> None:
    ex, _ = make()
    ex.on_event(BOOK, 0)
    o = ex.new_order(1, Outcome.YES, Side.BUY, 410_000, 100, OrderType.GTC)
    pending = ex.new_order(1, Outcome.YES, Side.BUY, 410_000, 100, OrderType.GTC)
    ex.arrive(o, 1)
    assert ex.account.reserved > 0
    assert ex.cancel(o, 2) and not ex.cancel(o, 3)
    ex.close(4)
    assert pending.status is OrderStatus.CANCELLED and pending.reason == "market closed"
    ex.arrive(pending, 5)  # arrives after close: stays cancelled
    assert pending.status is OrderStatus.CANCELLED and ex.account.reserved == 0


def test_arrival_after_close_or_grid_change() -> None:
    from predictsim.events import Band, GridChange

    ex, _ = make(PolymarketProfile())
    o = ex.new_order(1, Outcome.YES, Side.BUY, 410_000, 100, OrderType.GTC)
    ex.on_event(GridChange(2, (Band(100_000, 900_000, 100_000),)), 1)
    ex.arrive(o, 2)
    assert o.status is OrderStatus.REJECTED and "arrival" in o.reason
    ex2, _ = make()
    p = ex2.new_order(1, Outcome.YES, Side.BUY, 410_000, 100, OrderType.GTC)
    ex2.closed = True
    ex2.arrive(p, 2)
    assert p.reason == "market closed"
