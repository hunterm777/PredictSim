# PredictSim

Backtest a prediction-market strategy the way the exchange would actually have filled it.

PredictSim replays binary prediction-market order books and simulates how a strategy would really have filled, after queue position, latency, fees and settlement. It ships venue profiles for **Kalshi**, **Polymarket** and **Hyperliquid HIP-4**, current as of November 23, 2026.

It contains no API clients, no cloud storage and no data. You bring your own order-book history in a [documented schema](docs/schema.md); PredictSim turns it into honest PnL.

```
pip install predictsim            # core: Python 3.11+ and NumPy
pip install predictsim[gym]       # + Gymnasium environment
pip install predictsim[parquet]   # + Parquet loader (pyarrow)
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
* **Fees:** exact per venue, including Kalshi's per-order rounding accumulator. See the venue pages below.
* **Account:** fully collateralized. `net` positions for Kalshi; separate YES/NO `tokens` with split and merge for Polymarket and HIP-4. On settlement YES pays `settle_fraction`, NO pays 1 − `settle_fraction`. Open orders are cancelled at market close.
* **Results:** fill log, order log and equity curve (CSV export in `predictsim.io.csv`), with net and gross PnL, fees, fill count, maker share, max drawdown, return on capital and win rate across markets.
* **Gymnasium:** `predictsim.env.PredictSimEnv`, one episode per market, discrete or box actions, stepping on every book event or a fixed interval.
* **Deterministic:** the same events, config and seed give byte-identical fill logs (golden-file test).

## Limitations

* **No market impact.** Replayed data is never altered by simulated orders. Taken liquidity is hidden from later orders only until its level next updates.
* Binary markets only. No Polymarket neg-risk or HIP-4 multi-outcome questions.
* Fees are gross: Polymarket maker/taker rebate programs are not modelled.
* No connectivity of any kind: no API clients, recorders, live or paper trading. The test suite blocks sockets.

## Venues

* [Kalshi](docs/venues/kalshi.md)
* [Polymarket](docs/venues/polymarket.md)
* [Hyperliquid HIP-4](docs/venues/hyperliquid_hip4.md)

Venues change rules often, so every parameter is overridable: build a profile with your own rates, give a `MarketSpec` its own `fees`, or use `CustomFees(fn)`.

## Development

```
pip install -e ".[dev]"
ruff check . && mypy && pytest          # pytest enforces 90%+ coverage
python benchmarks/bench_replay.py       # target: 100k events/sec on one core
```

## Open questions

* Synthetic data generator: ship one so examples run with zero data, or keep examples on tiny fixtures (current)?
* Rust core: keep v1 pure Python, or plan a Rust matching core with Python bindings for v2?
* Multi-outcome markets (Polymarket neg-risk, HIP-4 questions with negate): v2 or never?
* Rebates: model Polymarket maker and taker rebate tiers as an optional parameter in v2?
* HIP-4 opening auction: model it, or start replay at continuous trading (current)?

## License

MIT
