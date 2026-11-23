# Polymarket

As of November 23, 2026. Implemented in `predictsim.venues.polymarket` and `predictsim.fees.polymarket`.

| Mechanic | Polymarket | Source |
| --- | --- | --- |
| Book | One book per token; YES and NO are separate tokens. Supply the YES book (a NO bid at q is a YES ask at 1 − q; the CSV loader converts `no_bid`/`no_ask` rows) | [Place orders](https://docs.polymarket.com/trading/place-orders) |
| Price grid | Per-market `tick_size` of 0.1, 0.01, 0.001 or 0.0001; can change mid-market (supply a `GridChange`) | same |
| Size | Shares with 2 decimals; per-market `min_order_size` (`MarketSpec.min_size`) | same |
| Collateral | pUSD (migrated from USDC.e) | |
| Positions | Separate YES/NO tokens with split and merge | |
| Settlement | 1 or 0 per share | |

## Fees

`fee = C × feeRate × p × (1 − p)`, takers only; makers never pay. Fees are rounded to 5 decimal places; the smallest fee charged is 0.00001, and anything smaller rounds to zero. The docs do not say which way to round, so PredictSim rounds down, which is what "anything smaller rounds to zero" implies. Source: [Trading fees](https://docs.polymarket.com/trading/fees).

Rates by category (`MarketSpec(fee_category=...)`), as listed in the PRD and on Polymarket's [November 2026 fee changes page](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026):

| Category key | Category | Taker rate |
| --- | --- | --- |
| `crypto_btc_5m_15m_updown` | Crypto: BTC 5-min and 15-min up/down | 0.05 |
| `crypto` | Crypto: all other | 0.01 |
| `sports`, `finance`, `tech`, `politics_elections`, `combos`, `other` | | 0.05 |
| `politics`, `economics`, `culture`, `weather`, `mentions` | | 0.01 |
| `geopolitics` | | 0 |

Polymarket's main fees page showed a different, older-looking table on November 23, 2026 (for example crypto 0.07, finance 0.04). Override the table with `PolymarketProfile(rates={...})` if your markets use other rates.

Maker and taker rebate programs are out of scope for v1; fees are gross.

Checked example: 100 shares at 0.50, rate 0.05 → 1.25.
