"""Parameter sweeps: run a strategy over a parameter grid and many markets,
in parallel, with results that do not depend on the number of workers.

Every (parameter set, market) pair is one independent run with
``config.initial_cash`` and ``config.seed``, so every parameter set sees the
same latency draws on the same market (common random numbers): differences
between parameter sets come from the parameters, not from the seed.

Workers are separate processes started with ``spawn`` on every platform
(forking a process that has threads can deadlock). The strategy factory and
each market's event source must be picklable: a module-level function or class, and either a list of
events or a module-level loader such as ``functools.partial(load_csv, path)``,
which each run calls to stream the events instead of copying them.
"""

from __future__ import annotations

import itertools
import multiprocessing
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

from predictsim.backtest import run_backtest
from predictsim.config import BacktestConfig
from predictsim.events import Event
from predictsim.metrics import BacktestResult, ManyResult, Summary
from predictsim.spec import MarketSpec
from predictsim.strategy import Strategy

Params = dict[str, Any]
EventSource = Sequence[Event] | Callable[[], Iterable[Event]]
Market = tuple[EventSource, MarketSpec]
Factory = Callable[..., Strategy]


def param_grid(axes: Mapping[str, Sequence[Any]]) -> list[Params]:
    """Every combination of ``axes``, in a fixed order: the last axis varies
    fastest, as in :func:`itertools.product`."""
    names = list(axes)
    if any(len(axes[n]) == 0 for n in names):
        raise ValueError("every axis needs at least one value")
    return [dict(zip(names, combo, strict=True)) for combo in itertools.product(*(axes[n] for n in names))]


@dataclass(frozen=True, slots=True)
class SweepRun:
    """One run: parameter set ``param_index`` on market ``market_index``."""

    param_index: int
    market_index: int
    params: Params
    result: BacktestResult


@dataclass(frozen=True, slots=True)
class SweepResult:
    """All runs, ordered by parameter set, then market."""

    params: list[Params]
    market_ids: list[str]
    runs: list[SweepRun]

    def results(self, param_index: int, markets: Iterable[int] | None = None) -> ManyResult:
        """One parameter set's runs on ``markets`` (market indices, in the order
        given; default all, in input order)."""
        n = len(self.market_ids)
        idx = range(n) if markets is None else list(dict.fromkeys(markets))
        return ManyResult([self.runs[param_index * n + m].result for m in idx])

    def summaries(self, markets: Iterable[int] | None = None) -> list[Summary]:
        """One summary per parameter set, in grid order."""
        chosen = None if markets is None else list(markets)
        return [self.results(p, chosen).summary() for p in range(len(self.params))]

    def best(self, metric: Callable[[Summary], float | None], markets: Iterable[int] | None = None) -> int:
        """Index of the parameter set with the highest ``metric`` (None counts
        as lowest; ties go to the earlier set in grid order)."""
        best, top = 0, None
        for i, summary in enumerate(self.summaries(markets)):
            score = metric(summary)
            if score is not None and (top is None or score > top):
                best, top = i, score
        return best


# ---- workers ------------------------------------------------------------------
_STATE: tuple[Factory, list[Params], list[Market], BacktestConfig] | None = None


def _init(factory: Factory, params: list[Params], markets: list[Market], config: BacktestConfig) -> None:
    global _STATE
    _STATE = (factory, params, markets, config)


def _job(job: tuple[int, int]) -> BacktestResult:
    assert _STATE is not None
    factory, params, markets, config = _STATE
    p, m = job
    source, spec = markets[m]
    events = source() if callable(source) else source
    return run_backtest(factory(**params[p]), events, spec, config)


def run_sweep(
    factory: Factory,
    grid: Sequence[Params],
    markets: Sequence[Market],
    config: BacktestConfig,
    workers: int | None = None,
) -> SweepResult:
    """Run ``factory(**params)`` for every parameter set in ``grid`` on every
    market. ``workers`` defaults to the CPU count; 1 runs in this process."""
    params, mkts = [dict(p) for p in grid], list(markets)
    if not params or not mkts:
        raise ValueError("a sweep needs at least one parameter set and one market")
    jobs = [(p, m) for p in range(len(params)) for m in range(len(mkts))]
    n = min(workers or os.cpu_count() or 1, len(jobs))
    if n <= 1:
        _init(factory, params, mkts, config)
        try:
            results = [_job(j) for j in jobs]
        finally:
            _init_clear()
    else:
        ctx = multiprocessing.get_context("spawn")
        init = (factory, params, mkts, config)
        with ProcessPoolExecutor(n, mp_context=ctx, initializer=_init, initargs=init) as pool:
            results = list(pool.map(_job, jobs, chunksize=max(1, len(jobs) // (4 * n))))
    runs = [SweepRun(p, m, params[p], r) for (p, m), r in zip(jobs, results, strict=True)]
    return SweepResult(params, [spec.market_id for _, spec in mkts], runs)


def _init_clear() -> None:
    global _STATE
    _STATE = None
