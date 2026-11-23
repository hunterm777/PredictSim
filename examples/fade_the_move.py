"""Toy taker strategy: when the mid jumps up by at least ``threshold``,
buy NO at the market; when it drops, buy YES. One position at a time.
Proves the API works; it is not alpha."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from predictsim import (
    BacktestConfig,
    BacktestResult,
    Context,
    KalshiProfile,
    MarketSpec,
    OrderBook,
    OrderType,
    Outcome,
    Side,
    Strategy,
    run_backtest,
    uniform_grid,
)
from predictsim.io.csv import load_csv

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_market.csv"


class FadeTheMove(Strategy):
    def __init__(self, threshold: int = 20_000, size: int = 300) -> None:
        self.threshold, self.size = threshold, size
        self.last_mid: Fraction | None = None

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        mid = book.mid()
        if mid is None:
            return
        flat = not any(ctx.positions.values()) and not ctx.open_orders
        if flat and self.last_mid is not None:
            move = mid - self.last_mid
            if move >= self.threshold:
                ctx.submit(Side.BUY, self.size, outcome=Outcome.NO, order_type=OrderType.MARKET)
            elif move <= -self.threshold:
                ctx.submit(Side.BUY, self.size, outcome=Outcome.YES, order_type=OrderType.MARKET)
        self.last_mid = mid


def run(config: BacktestConfig | None = None) -> BacktestResult:
    spec = MarketSpec("sample", KalshiProfile(), 0, 30_000, uniform_grid(10_000), 1, 1)
    cfg = config or BacktestConfig(initial_cash=100_000_000)
    return run_backtest(FadeTheMove(), load_csv(FIXTURE), spec, cfg)


if __name__ == "__main__":
    print(run().summary())
