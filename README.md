# PredictSim

Backtest a prediction-market strategy the way the exchange would actually have filled it.

PredictSim replays binary prediction-market order books and simulates how a strategy would really have filled, after queue position, latency, fees and settlement. It ships venue profiles for **Kalshi**, **Polymarket** and **Hyperliquid HIP-4**, checked against each venue's own docs on November 24, 2026.

It contains no API clients, no cloud storage and no data. You bring your own order-book history in a [documented schema](docs/schema.md); PredictSim turns it into honest PnL.

```
pip install predictsim            # core: Python 3.11+ and NumPy
pip install predictsim[gym]       # + Gymnasium environment
pip install predictsim[parquet]   # + Parquet loader (pyarrow)
pip install predictsim[pandas]    # + DataFrame export to pandas
pip install predictsim[polars]    # + DataFrame export to polars
```

## Quickstart

```python
import predictsim as ps
from predictsim.io.csv import load_csv


class BuyBelow(ps.Strategy):
    """Take 5 YES contracts once the ask is $0.42 or less."""

    def on_book(self, ctx: ps.Context, book: ps.OrderBook) -> None:
        ask = book.best_ask()
        if ask is not None and ask <= ps.to_micros("0.42") and not any(ctx.positions.values()):
            if not ctx.open_orders:
                ctx.submit(ps.Side.BUY, 500, ask, order_type=ps.OrderType.IOC)


grid = ps.uniform_grid(ps.to_micros("0.01"))
spec = ps.MarketSpec("sample", ps.KalshiProfile(), 0, 30_000, grid, size_step=1, min_size=1)
config = ps.BacktestConfig(initial_cash=ps.to_micros(100))
result = ps.run_backtest(BuyBelow(), load_csv("tests/fixtures/sample_market.csv"), spec, config)
print(result.summary())
```

Check a file before you backtest it:

```
predictsim validate my_market.csv --venue kalshi
```

## Research workflow

One strategy, many markets, many parameter sets, with honest out-of-sample numbers. See [docs/research.md](docs/research.md) for every option.

```python
import predictsim as ps
from predictsim.frames import sweep_frame
from predictsim.io.csv import load_csv

DAY = 86_400 * 10**9


class BuyAtOrBelow(ps.Strategy):
    def __init__(self, limit: int) -> None:
        self.limit = limit

    def on_book(self, ctx: ps.Context, book: ps.OrderBook) -> None:
        ask = book.best_ask()
        if ask is not None and ask <= self.limit and not any(ctx.positions.values()) and not ctx.open_orders:
            ctx.submit(ps.Side.BUY, 500, ask, order_type=ps.OrderType.IOC)


def main() -> None:
    grid = ps.uniform_grid(ps.to_micros("0.01"))
    markets = [  # your own files and specs; the same sample file twice here
        (
            load_csv("tests/fixtures/sample_market.csv"),
            ps.MarketSpec(m, ps.KalshiProfile(), 0, 30_000, grid, 1, 1),
        )
        for m in ("a", "b")
    ]
    config = ps.BacktestConfig(initial_cash=ps.to_micros(100), seed=7)

    params = ps.param_grid({"limit": [ps.to_micros("0.38"), ps.to_micros("0.42")]})
    sweep = ps.run_sweep(BuyAtOrBelow, params, markets, config)  # parallel, deterministic
    print(sweep_frame(sweep, backend="pandas"))  # or "polars"

    folds = ps.walk_forward_splits([spec for _, spec in markets], train_ns=DAY, test_ns=DAY)
    wf = ps.walk_forward(sweep, folds)  # pick on each fold's train markets, score on its test markets
    print(wf.summary())  # out-of-sample only (empty here: both samples share one window)

    book = ps.run_portfolio(BuyAtOrBelow(ps.to_micros("0.42")), markets, config)  # one shared cash balance
    print(book.summary(), book.trade_stats())
    print(book.performance(period_ns=1_000).sharpe)


if __name__ == "__main__":  # worker processes re-import this file
    main()
```

* **Sweep:** `run_sweep` runs every parameter set on every market in worker processes (`spawn`, plain `multiprocessing`), so the factory must be importable and a script needs the `__main__` guard; `workers=1` runs in-process. Every run uses `config.seed`, so results are byte-identical whatever the worker count, and parameter sets are compared on the same latency draws.
* **Walk-forward:** `walk_forward_splits` makes rolling or anchored folds over markets by open time. A train market must close at or before its fold's test window starts, so no market is in both. `walk_forward` picks the best parameter set on each fold's train markets and reports only its test-market results.
* **Portfolio:** `run_portfolio` replays many markets in one global time order against one cash balance, so an order in one market can be refused because cash is tied up in another. Each market gets its own seed derived from `config.seed`.
* **Stats:** `performance(period_ns, periods_per_year=None)` gives Sharpe and Sortino from the equity curve sampled at a fixed period; nothing is annualized unless you say how many periods a year has. `trade_stats()` breaks results into round trips (flat to flat, or to settlement): count, win rate, average win and loss, profit factor, holding time.
* **DataFrames:** `predictsim.frames` exports fills, orders, round trips, equity and sweep summaries to pandas or polars. Money stays in integer micro-dollars.
* **Multi-outcome:** Polymarket negative-risk events and HIP-4 questions run in portfolio mode with `groups=[ps.NegRiskEvent(...)]` or `[ps.HIP4Question(...)]`. Each outcome is its own market and book; the group adds the venue's conversions (`ctx.convert`, `ctx.negate`, `ctx.merge_question`) and checks that exactly one outcome settles YES. See the venue pages for what the docs specify and what they leave open.

## How it works

Everything inside PredictSim is an integer in YES-price space:

| Quantity | Unit | Example |
| --- | --- | --- |
| Price, money | micro-dollars (1e-6) | $0.42 = `420_000` |
| Size | centi-contracts (1e-2) | 1.5 contracts = `150` |
| Time | nanoseconds since the Unix epoch, UTC | |

The book holds YES bids and YES asks. A Kalshi NO bid at $0.30 is a YES ask at $0.70; buying NO at q is selling YES at 1 − q. Strategies can still send NO orders; they are translated at the edge. Fee and PnL math never touches a float.

* **Orders:** GTC limit, immediate-or-cancel, fill-or-kill, post-only, and market (an IOC limit at the worst valid price). Validated against the current grid, size step, minimum size and available cash. Sequential integer ids; cancel and cancel-all.
* **Latency:** separate submit, cancel and market-data delays, each fixed, uniform or lognormal, seeded. An order is live only after its submit delay, and a cancel can lose the race to a fill.
* **Taker fills:** a marketable order walks the book level by level up to its limit. Size it takes is removed from a shadow of the book until that level next updates, so it cannot be taken twice.
* **Maker fills:** a resting order joins the back of its level. Trades at its price drain the queue ahead first, then fill it. Cancels at the level move the queue by the chosen model: `pessimistic`, `proportional` or `optimistic`. If the opposite best price reaches its price, it fills in full at its own price.
* **Fees:** exact per venue from each market's own fee parameters, including Kalshi's per-order rounding accumulator. See the venue pages below.
* **Account:** fully collateralized. Kalshi keeps one signed position per market (positive YES, negative NO); Polymarket and HIP-4 keep separate YES and NO tokens with split and merge. On settlement YES pays `settle_fraction`, NO pays 1 − `settle_fraction`. Open orders are cancelled at market close.
* **Results:** fill log, order log and equity curve (CSV export in `predictsim.io.csv`), with net and gross PnL, fees, fill count, maker share, max drawdown, return on capital and win rate across markets.
* **Gymnasium:** `predictsim.env.PredictSimEnv`, one episode per market, discrete or box actions, stepping on every book event or a fixed interval.
* **Deterministic:** the same events, config and seed give byte-identical fill logs (golden-file test).

## Limitations

* **No market impact.** Replayed data is never altered by simulated orders. Taken liquidity is hidden from later orders only until its level next updates.
* Multi-outcome conversions carry no fee, and their exact collateral rules are only what the venues publish (see the venue pages). HIP-4 multi-outcome questions are not yet on mainnet.
* Fees are gross: Polymarket maker/taker rebate programs are not modelled.
* No connectivity of any kind: no API clients, recorders, live or paper trading. The test suite blocks sockets.

## Venues

* [Kalshi](docs/venues/kalshi.md)
* [Polymarket](docs/venues/polymarket.md)
* [Hyperliquid HIP-4](docs/venues/hyperliquid_hip4.md)

Research tools (sweep, walk-forward, portfolio, stats, DataFrames): [docs/research.md](docs/research.md).

Fees are set per market on every venue (Kalshi series multipliers, Polymarket `feeSchedule`, HIP-4 deployer scale), so each profile takes the market's parameters. To replace a venue's fee model, give a `MarketSpec` its own `fees`, e.g. `CustomFees(fn)`.

## Development

```
pip install -e ".[dev]"
ruff check . && mypy && pytest          # pytest enforces 99.9% coverage
python benchmarks/bench_replay.py       # target: 100k events/sec on one core
```

On the machine this was built on, one core replays about 650,000 events/sec with no strategy and about 180,000 with a strategy quoting under latency.

## Open questions

* Synthetic data generator: ship one so examples run with zero data, or keep examples on tiny fixtures (current)?
* Rust core: keep v1 pure Python, or plan a Rust matching core with Python bindings for v2?
* Rebates: model Polymarket maker and taker rebate tiers as an optional parameter in v2?
* HIP-4 opening auction: model it, or start replay at continuous trading (current)?

## License

MIT
