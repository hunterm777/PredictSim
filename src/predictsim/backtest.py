"""Run markets: :func:`run_backtest` for one, :func:`run_many` for several
in sequence. The event loop itself is :class:`predictsim.engine.Engine`."""

from __future__ import annotations

from collections.abc import Iterable

from predictsim.config import BacktestConfig
from predictsim.engine import Engine
from predictsim.events import Event
from predictsim.metrics import BacktestResult, ManyResult
from predictsim.spec import MarketSpec
from predictsim.strategy import Strategy

__all__ = ["BacktestConfig", "Engine", "run_backtest", "run_many"]


def run_backtest(
    strategy: Strategy,
    events: Iterable[Event],
    spec: MarketSpec,
    config: BacktestConfig,
    cash: int | None = None,
) -> BacktestResult:
    """Run one market from open to the end of its events."""
    engine = Engine(strategy, events, spec, config, cash)
    engine.start()
    while engine.step():
        pass
    return engine.result()


def run_many(
    strategy: Strategy,
    markets: Iterable[tuple[Iterable[Event], MarketSpec]],
    config: BacktestConfig,
    carry_cash: bool = True,
) -> ManyResult:
    """Run markets in sequence. With ``carry_cash`` each market starts with
    the previous market's final cash; otherwise each starts with
    ``config.initial_cash``. Positions are never carried between markets."""
    results: list[BacktestResult] = []
    cash = config.initial_cash
    for events, spec in markets:
        res = run_backtest(strategy, events, spec, config, cash if carry_cash else None)
        results.append(res)
        cash = res.final_cash
    return ManyResult(results)
