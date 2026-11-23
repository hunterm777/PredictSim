"""Toy maker strategy: rest a bid at the best bid while flat, then rest an
ask at the best ask to exit, re-quoting when the best price moves away.
Proves the API works; it is not alpha."""

from __future__ import annotations

from pathlib import Path

from predictsim import (
    BacktestConfig,
    BacktestResult,
    Context,
    KalshiProfile,
    MarketSpec,
    OrderBook,
    Outcome,
    Side,
    Strategy,
    run_backtest,
    uniform_grid,
)
from predictsim.io.csv import load_csv

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_market.csv"


class SpreadCapture(Strategy):
    def __init__(self, size: int = 500) -> None:
        self.size = size

    def on_book(self, ctx: Context, book: OrderBook) -> None:
        held = ctx.positions[Outcome.YES]
        bid, ask = book.best_bid(), book.best_ask()
        live = ctx.open_orders
        if live:
            target = ask if live[0].side is Side.SELL else bid
            if target is not None and live[0].px != target:
                ctx.cancel_all()
            return
        if held and ask is not None:
            ctx.submit(Side.SELL, held, ask)
        elif not held and bid is not None:
            ctx.submit(Side.BUY, self.size, bid)


def spec() -> MarketSpec:
    return MarketSpec("sample", KalshiProfile(), 0, 30_000, uniform_grid(10_000), 1, 1)


def run(config: BacktestConfig | None = None) -> BacktestResult:
    cfg = config or BacktestConfig(initial_cash=100_000_000)
    return run_backtest(SpreadCapture(), load_csv(FIXTURE), spec(), cfg)


if __name__ == "__main__":
    print(run().summary())
