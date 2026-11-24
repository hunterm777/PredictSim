"""Walk-forward analysis: choose parameters on in-sample markets, score them
on the out-of-sample markets that follow, and roll forward.

Splits are by time over markets. Fold ``k`` tests the markets that open in
``[test_start, test_start + test_ns)``, where ``test_start = start + train_ns
+ k * step_ns``. Its in-sample markets open at or after the train start
(``test_start - train_ns``, or ``start`` when ``anchored``) and close at or
before ``test_start``, so no in-sample market overlaps the test window.
Folds with no in-sample or no out-of-sample market are skipped.

:func:`walk_forward` works on a finished :class:`~predictsim.sweep.SweepResult`
over all markets: every (parameter set, market) run is independent of the
fold, so one sweep serves every fold and nothing is run twice.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from predictsim.metrics import ManyResult, Summary
from predictsim.spec import MarketSpec
from predictsim.sweep import Params, SweepResult

Metric = Callable[[Summary], float | None]


@dataclass(frozen=True, slots=True)
class Fold:
    """One split: market indices, in time order, and the test window."""

    index: int
    train: tuple[int, ...]
    test: tuple[int, ...]
    train_start: int
    test_start: int
    test_end: int


def walk_forward_splits(
    specs: Sequence[MarketSpec],
    train_ns: int,
    test_ns: int,
    step_ns: int | None = None,
    anchored: bool = False,
    start: int | None = None,
) -> list[Fold]:
    """Rolling (or anchored) walk-forward folds over markets by open time.
    ``step_ns`` defaults to ``test_ns``, so test windows do not overlap; a
    smaller step tests some markets in more than one fold."""
    step = test_ns if step_ns is None else step_ns
    if train_ns <= 0 or test_ns <= 0 or step <= 0:
        raise ValueError("train_ns, test_ns and step_ns must be positive")
    if not specs:
        return []
    order = sorted(range(len(specs)), key=lambda i: (specs[i].open_ts, i))
    origin = min(s.open_ts for s in specs) if start is None else start
    last_open = max(s.open_ts for s in specs)
    folds: list[Fold] = []
    k = 0
    while (test_start := origin + train_ns + k * step) <= last_open:
        test_end = test_start + test_ns
        train_start = origin if anchored else test_start - train_ns
        train = tuple(i for i in order if specs[i].open_ts >= train_start and specs[i].close_ts <= test_start)
        test = tuple(i for i in order if test_start <= specs[i].open_ts < test_end)
        if train and test:
            folds.append(Fold(len(folds), train, test, train_start, test_start, test_end))
        k += 1
    return folds


def net_pnl(summary: Summary) -> float:
    """Default selection metric: net PnL."""
    return float(summary.net_pnl)


@dataclass(frozen=True, slots=True)
class FoldResult:
    """The parameter set chosen in-sample and how it did out of sample."""

    fold: Fold
    param_index: int
    params: Params
    in_sample: Summary
    out_of_sample: Summary


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    folds: list[FoldResult]
    oos: ManyResult

    def summary(self) -> Summary:
        """Out-of-sample summary over every fold's test markets, in order."""
        return self.oos.summary()

    def in_sample(self) -> list[Summary]:
        return [f.in_sample for f in self.folds]


def walk_forward(sweep: SweepResult, folds: Sequence[Fold], metric: Metric = net_pnl) -> WalkForwardResult:
    """For each fold, pick the parameter set with the best in-sample
    ``metric`` (ties to the earlier set) and record its out-of-sample runs."""
    out: list[FoldResult] = []
    oos = []
    for fold in folds:
        p = sweep.best(metric, fold.train)
        test = sweep.results(p, fold.test)
        oos.extend(test.results)
        out.append(
            FoldResult(fold, p, sweep.params[p], sweep.results(p, fold.train).summary(), test.summary())
        )
    return WalkForwardResult(out, ManyResult(oos))
