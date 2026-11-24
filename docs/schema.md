# Event schema

PredictSim replays a stream of events for one market. Supply them as any Python iterable of event objects, or as a CSV or Parquet file.

## Units

| Quantity | Unit |
| --- | --- |
| Price, money | integer micro-dollars (1e-6): $0.42 = `420_000` |
| Size | integer centi-contracts (1e-2): 1.5 contracts = `150` |
| Time | integer nanoseconds since the Unix epoch, UTC |

All prices are **YES prices**. Use `predictsim.to_micros("0.42")` and `predictsim.to_centis("1.5")` to convert exactly; values that are not whole units are refused.

## Events

| Event | Fields | Meaning |
| --- | --- | --- |
| `Snapshot` | `ts, bids[(px, sz)], asks[(px, sz)]` | Full replace of the book |
| `Delta` | `ts, side (BookSide.BID/ASK), px, new_sz` | One level set to a new size; 0 removes it |
| `Trade` | `ts, px, sz, aggressor (Side.BUY/SELL)` | A print on the venue; a SELL aggressor hits bids |
| `GridChange` | `ts, bands[Band(start, end, step)]` | Tick grid changed mid-market |
| `Settle` | `ts, settle_fraction` | Resolved: `1_000_000` = YES, `0` = NO, values between allowed |

Timestamps must not decrease. With `BacktestConfig(strict=True)` (the default) a crossed or off-grid book event raises `BookError` naming the event index; with `strict=False` it is logged and skipped.

## MarketSpec

| Field | Meaning |
| --- | --- |
| `market_id` | Any string |
| `venue` | `KalshiProfile(...)`, `PolymarketProfile(fee_rate=...)` or `HIP4Profile(...)`, with the market's own fee parameters |
| `open_ts`, `close_ts` | Orders are accepted from open; open orders are cancelled at close |
| `grid` | Initial price grid: `Grid((Band(start, end, step), ...))` or `uniform_grid(step)` |
| `size_step`, `min_size` | Order size granularity and minimum, in centi-contracts |
| `fees` | Optional fee model that replaces the venue's, e.g. `CustomFees(fn)` |

A price is on the grid if it is strictly between $0 and $1 and lies on some band's `start + k * step` lattice within `[start, end]`. Bands may share endpoints.

## CSV and Parquet files

One row per event, or per level for snapshots. Columns:

| Column | Used by | Format |
| --- | --- | --- |
| `ts` | all | integer nanoseconds |
| `type` | all | `snapshot`, `delta`, `trade`, `grid` or `settle` |
| `side` | snapshot, delta | `bid`, `ask` (YES book), `no_bid`, `no_ask` (NO book, converted to YES) |
| `side` | trade | aggressor: `buy`, `sell` (YES), `no_buy`, `no_sell` (NO, converted to YES) |
| `px` | snapshot, delta, trade | decimal dollars, e.g. `0.42` |
| `sz` | snapshot, delta, trade | decimal contracts, e.g. `1.5` |
| `start`, `end`, `step` | grid | decimal dollars |
| `settle_fraction` | settle | decimal between 0 and 1 |

Consecutive `snapshot` rows with the same `ts` form one snapshot; a snapshot row with an empty `side` is an empty book. Consecutive `grid` rows with the same `ts` form one grid change. If your columns have other names, pass a mapping from these names to yours:

```python
from predictsim.io.csv import load_csv
from predictsim.io.parquet import load_parquet  # needs predictsim[parquet]

events = load_csv("market.csv", mapping={"ts": "timestamp_ns", "px": "price"})
```

Kalshi publishes two bid-only arrays; `predictsim.venues.kalshi.snapshot_from_kalshi` and `delta_from_kalshi` convert them to YES space directly.

## Validation

```
predictsim validate FILE --venue {kalshi,polymarket,hip4} [--tick 0.001] [--map ts=timestamp_ns ...]
```

It reports, by event index: timestamps going backwards, prices off the grid, negative sizes, crossed books, bad trades and events after settlement. Exit code 0 means clean, 1 means problems were found, 2 means the file could not be read. In Python, use `predictsim.io.validate.validate(events, spec)`.
