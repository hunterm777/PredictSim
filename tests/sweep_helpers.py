"""Picklable strategies, loaders and market builders for the sweep,
walk-forward and portfolio tests (worker processes import this module)."""

from __future__ import annotations

from predictsim import (
    Context,
    Event,
    KalshiProfile,
    MarketSpec,
    OrderBook,
    Outcome,
    Settle,
    Side,
    Snapshot,
    Strategy,
    Trade,
    uniform_grid,
)
from predictsim.events import BookSide, Delta


class BuyAtOrBelow(Strategy):
    """Rest one bid of ``size`` at ``px`` while flat and without orders."""

    def __init__(self, px: int, size: int = 100) -> None:
        self.px, self.size = px, size

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        if not ctx.open_orders and not ctx.positions[Outcome.YES]:
            ctx.submit(Side.BUY, self.size, self.px)


def kalshi_spec(market_id: str, open_ts: int = 0, close_ts: int = 1_000) -> MarketSpec:
    return MarketSpec(market_id, KalshiProfile(), open_ts, close_ts, uniform_grid(10_000), 1, 1)


def market_events(open_ts: int = 0, trade_px: int = 400_000, settle: int = 1_000_000) -> list[Event]:
    """Book at 0.40/0.42, a sell print at ``trade_px``, then settlement."""
    t = open_ts
    return [
        Snapshot(t + 10, ((400_000, 1_000), (390_000, 1_000)), ((420_000, 1_000),)),
        Trade(t + 200, trade_px, 5_000, Side.SELL),
        Delta(t + 210, BookSide.BID, trade_px, 0),
        Settle(t + 900, settle),
    ]


def loader() -> list[Event]:
    return market_events()
