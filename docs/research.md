# Research workflow

Sweeps, walk-forward validation, portfolio mode and statistics. All money is integer micro-dollars and all times are nanoseconds, as everywhere in PredictSim.

## Sweep

```python
grid = ps.param_grid({"limit": [380_000, 420_000], "size": [100, 500]})  # product, in key order
sweep = ps.run_sweep(factory, grid, markets, config, workers=None)
```

* `factory(**params)` builds one strategy. `markets` is a list of `(events, spec)`; `events` is a list of events or a zero-argument callable that loads them, so each worker can read its own files.
* Jobs run in worker processes started with `spawn` (plain `multiprocessing`; forking a process with threads can deadlock). The factory and event sources must pickle, and a script needs `if __name__ == "__main__":`. `workers=None` uses every CPU; `workers=1` runs in this process.
* Every run uses `config.seed`. Results are the same for any worker count, and every parameter set sees the same latency draws (common random numbers), so differences between sets come from the parameters.
* `sweep.results(i)` gives a `ManyResult` for parameter set `i`, `sweep.summaries()` one `Summary` per set, and `sweep.best(metric)` the index of the best set (ties go to the earlier set; a `None` metric ranks last). All three take an optional list of market indices.

## Walk-forward

```python
folds = ps.walk_forward_splits(specs, train_ns=30 * DAY, test_ns=7 * DAY, step_ns=None, anchored=False)
wf = ps.walk_forward(sweep, folds, metric=lambda s: s.net_pnl)
wf.summary()  # out-of-sample results only
wf.in_sample()  # each fold's best in-sample summary, for comparison
```

* Folds are over markets by open time. A fold's test markets open in `[test_start, test_end)`; its train markets open in the train window and close at or before `test_start`, so no market is in both and no train market overlaps the test window.
* `step_ns` defaults to `test_ns`, so test windows do not overlap. `anchored=True` keeps every train window starting at the first open time (or `start`, if given).
* Folds with no train or no test markets are skipped.
* `walk_forward` picks the best parameter set on each fold's train markets with `metric` and keeps only that set's results on the fold's test markets. One sweep serves every fold.

## Portfolio

```python
result = ps.run_portfolio(strategy_or_factory, markets, config, groups=())
```

* All markets replay in one global time order and share one cash balance of `config.initial_cash`. Reservations for open orders in one market reduce what every other market can spend.
* Pass one strategy instance to see every market, or a factory `factory(spec)` for one strategy per market.
* Each market draws latency from its own stream seeded from `(config.seed, market index)`, so the result does not depend on how events interleave.
* `result.summary()` is the whole book; `result.breakdown()` gives each market's PnL (zero-based, since cash is shared). `result.equity` is the shared equity curve.
* `groups` binds multi-outcome markets: `NegRiskEvent` for Polymarket, `HIP4Question` for HIP-4. See the venue pages.

## Statistics

```python
perf = result.performance(period_ns=DAY, periods_per_year=365, risk_free=0.0)
trades = result.trade_stats()
```

* `performance` samples the equity curve at the end of each period and uses simple returns. Sharpe is the mean excess return over its standard deviation (ddof 1). Sortino divides by the downside deviation `sqrt(mean(min(r - target, 0)^2))`. Both are per period unless you pass `periods_per_year`, which scales them by its square root. Both are `None` with fewer than two periods or zero deviation.
* `trade_stats` works on round trips: from flat to flat, or to settlement. A trip still open at the end is valued at the mark. It reports count, wins, losses, win rate, total PnL and fees, expectancy, average win and loss, profit factor and average holding time.
* Available on `BacktestResult`, `ManyResult` (markets chained in order) and `PortfolioResult`.

## DataFrames

```
pip install predictsim[pandas]    # or predictsim[polars]
```

`predictsim.frames` has `fills_frame`, `orders_frame`, `trips_frame`, `equity_frame` and `sweep_frame`, each with `backend="pandas"` or `"polars"`. Money columns stay integer micro-dollars.
