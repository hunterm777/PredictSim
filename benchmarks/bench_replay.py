"""Replay throughput: events per second on one core, pure Python.

Builds a synthetic stream (seeded) of deltas and trades on a 1-cent grid
around $0.50 and replays it twice: with a strategy that does nothing (the
engine alone), and with one that keeps a bid quoted at the best bid under
5 ns submit and data latency (queue tracking, fills and delayed data).
Usage: python benchmarks/bench_replay.py [N]
"""

from __future__ import annotations

import sys
import time

import numpy as np

from predictsim import (
    BacktestConfig,
    BookSide,
    Context,
    Delta,
    Event,
    Fixed,
    KalshiProfile,
    LatencyConfig,
    MarketSpec,
    OrderBook,
    Side,
    Snapshot,
    Strategy,
    Trade,
    run_backtest,
    uniform_grid,
)

TARGET = 100_000


def make_events(n: int, seed: int = 0) -> list[Event]:
    rng = np.random.default_rng(seed)
    bids = tuple((p * 10_000, 1_000) for p in range(40, 50))
    asks = tuple((p * 10_000, 1_000) for p in range(51, 61))
    events: list[Event] = [Snapshot(0, bids, asks)]
    sides = rng.integers(0, 2, n)
    offsets = rng.integers(0, 10, n)
    sizes = rng.integers(0, 2_000, n)
    kinds = rng.random(n)
    for i in range(n):
        ts = i + 1
        if sides[i]:
            px = (49 - int(offsets[i])) * 10_000
            side = BookSide.BID
        else:
            px = (51 + int(offsets[i])) * 10_000
            side = BookSide.ASK
        if kinds[i] < 0.2:
            aggressor = Side.SELL if side is BookSide.BID else Side.BUY
            events.append(Trade(ts, px, int(sizes[i]) + 1, aggressor))
        else:
            events.append(Delta(ts, side, px, int(sizes[i])))
    return events


class QuoteBestBid(Strategy):
    """Keep one 1-contract bid at the best bid; re-quote when it moves."""

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        bid = book.best_bid()
        live = ctx.open_orders
        if live:
            if live[0].px != bid:
                ctx.cancel_all()
        elif bid is not None:
            ctx.submit(Side.BUY, 100, bid)


def measure(label: str, strategy: Strategy, events: list[Event], config: BacktestConfig) -> float:
    spec = MarketSpec("bench", KalshiProfile(), 0, len(events) + 1, uniform_grid(10_000), 1, 1)
    start = time.perf_counter()
    run_backtest(strategy, events, spec, config)
    rate = len(events) / (time.perf_counter() - start)
    print(f"{label}: {len(events):,} events, {rate:,.0f} events/sec (target {TARGET:,})")
    return rate


def main(n: int = 500_000) -> tuple[float, float]:
    events = make_events(n)
    idle = measure("replay only", Strategy(), events, BacktestConfig(initial_cash=0))
    latency = LatencyConfig(submit=Fixed(5), data=Fixed(5))
    busy = measure("quoting strategy", QuoteBestBid(), events, BacktestConfig(10**15, latency))
    return idle, busy


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500_000)
