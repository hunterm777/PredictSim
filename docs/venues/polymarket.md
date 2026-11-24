# Polymarket

As of November 24, 2026. Implemented in `predictsim.venues.polymarket` and `predictsim.fees.polymarket`.

| Mechanic | Polymarket | Source |
| --- | --- | --- |
| Tokens | "Both represent Yes and No outcomes as ERC-1155 balances": YES and NO are separate balances, and you can hold both | [Positions & tokens](https://docs.polymarket.com/concepts/positions-tokens) |
| Split and merge | "Every 1 pUSD produces 1 YES token and 1 NO token"; "Every 1 YES token and 1 NO token returns 1 pUSD" | [Merge](https://docs.polymarket.com/developers/CTF/merge) |
| Book | A buy of YES at $0.60 and a buy of NO at $0.40 match: "1 pUSD of collateral creates a complete set". PredictSim keeps one YES-space book; a NO bid at q is a YES ask at 1 − q | [Prices & orderbook](https://docs.polymarket.com/concepts/prices-orderbook) |
| Tick size | Per market `orderPriceMinTickSize`: 0.1, 0.01, 0.005, 0.0025, 0.001 or 0.0001 (give it as the grid; a change is a `GridChange` event) | [Market details](https://docs.polymarket.com/market-data/market-details) |
| Minimum order | Per market `orderMinSize`, in USDC: "The CLOB rejects orders below this threshold" (`PolymarketProfile(min_notional=...)`) | same |
| Settlement | Winning token $1, losing $0; a binary market can "resolve to a split payout" | Positions & tokens |

Selling needs tokens you hold; to sell what you don't hold, split first or buy the other outcome.

## Fees

From [Trading fees](https://docs.polymarket.com/trading/fees): `fee = C × feeRate × p × (1 - p)`. "Makers are never charged fees. Only takers pay fees." "Fees are rounded to 5 decimal places." "The smallest fee charged is 0.00001 USDC. Anything smaller rounds to zero." The docs give no rounding direction, so PredictSim rounds down, which is what "anything smaller rounds to zero" implies.

The rate is per market. Each market exposes `feesEnabled` and `feeSchedule` with `rate`, `exponent` and `takerOnly` ([Market details](https://docs.polymarket.com/market-data/market-details)). Give them to the profile:

```python
PolymarketProfile(fee_rate="0.05", fee_exponent=1, taker_only=True, fees_enabled=True)
```

`exponent` is "applied to the price component of the fee curve"; PredictSim reads that as `(p × (1 − p)) ** exponent`. The docs' example and the fees page formula use 1.

Polymarket's two fee pages list different rates by category (for example crypto 0.07 on [Trading fees](https://docs.polymarket.com/trading/fees), 0.01 on [the November 2026 page](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026)) and neither shows a date. PredictSim ships no category table: use the market's own `feeSchedule.rate`.

Maker rebates are out of scope for v1; fees are gross. `secondsDelay` (a delay before a marketable order can match) is not modelled; use submit latency.

Checked example: 100 shares at 0.50, rate 0.05 → 1.25.

## Negative-risk events (multi-outcome)

Implemented in `predictsim.multi` and run in portfolio mode: `run_portfolio(..., groups=[NegRiskEvent(("a", "b", "other"))])`. Each outcome is its own binary market with its own book, events, fees and `MarketSpec`.

| Mechanic | Polymarket | Source |
| --- | --- | --- |
| Settlement | "Exactly one market in the group resolves Yes, while every other market resolves No." PredictSim checks this when the group finishes | [Negative risk](https://docs.polymarket.com/concepts/negative-risk) |
| Conversion | "A No share in any market can be converted into 1 Yes share in every other market": `ctx.convert(size)` takes `size` NO from the calling market and adds `size` YES to every other market of the event | same |
| Split and merge | Per market, as for any binary market | [Markets & events](https://docs.polymarket.com/concepts/markets-events) |

Not specified by Polymarket's docs, so chosen by PredictSim:

* Conversion fee: none is published, so none is charged.
* Conversion after any market of the event has settled: refused.
* Reversibility: there is no reverse conversion.
* Collateral when converting No shares from several markets at once: not modelled. Each `convert` call works on one market.
* A 50/50 resolution inside an event: refused, since exactly one market must resolve Yes.
* "Other" and placeholder markets: list them in the event like any market; how a placeholder is later clarified is not modelled.
* Per-market PnL inside an event is an attribution, because a conversion moves tokens between markets with no cash. The event total is exact.
