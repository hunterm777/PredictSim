"""Parameter sweeps and walk-forward selection."""

from __future__ import annotations

import pytest

from predictsim import (
    BacktestConfig,
    LatencyConfig,
    LogNormal,
    MarketSpec,
    param_grid,
    run_sweep,
    walk_forward,
    walk_forward_splits,
)
from predictsim.walkforward import net_pnl
from tests.sweep_helpers import BuyAtOrBelow, kalshi_spec, loader, market_events

CFG = BacktestConfig(100_000_000, LatencyConfig(submit=LogNormal(20, 0.5), data=LogNormal(5, 0.5)), seed=3)
PX = [390_000, 400_000, 410_000]


def markets(n: int = 3) -> list[tuple[object, MarketSpec]]:
    return [(market_events(i * 1_000), kalshi_spec(f"m{i}", i * 1_000, i * 1_000 + 1_000)) for i in range(n)]


def test_param_grid_order() -> None:
    assert param_grid({"a": [1, 2], "b": ["x", "y"]}) == [
        {"a": 1, "b": "x"},
        {"a": 1, "b": "y"},
        {"a": 2, "b": "x"},
        {"a": 2, "b": "y"},
    ]
    with pytest.raises(ValueError, match="at least one value"):
        param_grid({"a": []})


def test_sweep_is_identical_for_any_worker_count() -> None:
    grid = param_grid({"px": PX})
    one = run_sweep(BuyAtOrBelow, grid, markets(), CFG, workers=1)  # type: ignore[arg-type]
    many = run_sweep(BuyAtOrBelow, grid, markets(), CFG, workers=3)  # type: ignore[arg-type]
    assert [r.result.fills for r in one.runs] == [r.result.fills for r in many.runs]
    assert [r.result.equity for r in one.runs] == [r.result.equity for r in many.runs]
    assert [(r.param_index, r.market_index) for r in one.runs] == [(p, m) for p in range(3) for m in range(3)]
    assert one.market_ids == ["m0", "m1", "m2"] and one.params == grid


def test_sweep_results_and_best() -> None:
    sweep = run_sweep(BuyAtOrBelow, param_grid({"px": PX}), markets(), CFG, workers=1)  # type: ignore[arg-type]
    # only the bid resting at 0.40 trades with the sell print at 0.40
    assert [s.n_fills for s in sweep.summaries()] == [0, 3, 0]
    assert sweep.best(net_pnl) == 1
    assert sweep.best(lambda s: None) == 0
    assert sweep.best(lambda s: 1.0) == 0  # ties go to the earlier set
    picked = sweep.results(1, [2, 0, 2])
    assert [r.market_id for r in picked.results] == ["m2", "m0"]
    assert sweep.summaries([0])[1].n_fills == 1


def test_sweep_streams_events_from_a_loader() -> None:
    sweep = run_sweep(BuyAtOrBelow, [{"px": 400_000}], [(loader, kalshi_spec("l"))], CFG)
    assert sweep.runs[0].result.net_pnl == 600_000


def test_sweep_needs_params_and_markets() -> None:
    with pytest.raises(ValueError, match="at least one"):
        run_sweep(BuyAtOrBelow, [], markets(), CFG)  # type: ignore[arg-type]


def specs(opens: list[int], length: int = 100) -> list[MarketSpec]:
    return [kalshi_spec(f"s{i}", t, t + length) for i, t in enumerate(opens)]


def test_rolling_splits() -> None:
    folds = walk_forward_splits(specs([0, 100, 200, 300, 400, 500]), train_ns=200, test_ns=100)
    assert [(f.train, f.test) for f in folds] == [
        ((0, 1), (2,)),
        ((1, 2), (3,)),
        ((2, 3), (4,)),
        ((3, 4), (5,)),
    ]
    assert (folds[0].train_start, folds[0].test_start, folds[0].test_end) == (0, 200, 300)


def test_anchored_splits_with_step() -> None:
    folds = walk_forward_splits(specs([0, 100, 200, 300, 400]), 200, 100, step_ns=200, anchored=True)
    assert [(f.train, f.test) for f in folds] == [((0, 1), (2,)), ((0, 1, 2, 3), (4,))]


def test_in_sample_markets_never_overlap_the_test_window() -> None:
    # s1 opens in the train window but closes after the test window starts
    s = [kalshi_spec("s0", 0, 100), kalshi_spec("s1", 150, 260), kalshi_spec("s2", 200, 300)]
    (fold,) = walk_forward_splits(s, 200, 100)
    assert fold.train == (0,) and fold.test == (2,)


def test_empty_folds_are_skipped_and_inputs_checked() -> None:
    folds = walk_forward_splits(specs([0, 500, 600]), 100, 100, start=0)
    assert [(f.index, f.train, f.test) for f in folds] == [(0, (1,), (2,))]
    assert walk_forward_splits([], 100, 100) == []
    with pytest.raises(ValueError, match="positive"):
        walk_forward_splits(specs([0]), 0, 100)


def test_walk_forward_picks_in_sample_and_scores_out_of_sample() -> None:
    mkts = markets(4)
    sweep = run_sweep(BuyAtOrBelow, param_grid({"px": PX}), mkts, CFG, workers=1)  # type: ignore[arg-type]
    folds = walk_forward_splits([s for _, s in mkts], train_ns=2_000, test_ns=1_000)
    wf = walk_forward(sweep, folds)
    assert [(f.fold.train, f.fold.test, f.param_index) for f in wf.folds] == [
        ((0, 1), (2,), 1),
        ((1, 2), (3,), 1),
    ]
    assert [r.market_id for r in wf.oos.results] == ["m2", "m3"]
    assert wf.summary() == sweep.results(1, [2, 3]).summary()
    assert wf.in_sample()[0] == sweep.results(1, [0, 1]).summary()
    assert wf.folds[0].params == {"px": 400_000} and wf.folds[0].out_of_sample.net_pnl == 600_000
