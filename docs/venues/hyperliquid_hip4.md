# Hyperliquid HIP-4

As of November 24, 2026. Implemented in `predictsim.venues.hip4` and `predictsim.fees.hip4`.

| Mechanic | HIP-4 | Source |
| --- | --- | --- |
| Tokens | "Each outcome market consists of two sides, each with a token", usually Yes and No: separate balances, linked by merge | [HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets) |
| Book | "The order books of Yes and No tokens for the same outcome are merged to share liquidity"; "an order to buy Yes at price `p` is equivalent to an order to sell No at price `1-p`" | same |
| Settlement | "Yes to `settleFraction` quote tokens and No to `1 - settleFraction` quote tokens". Outcomes in a question settle to exactly 0 or 1 | same; [deployer actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions) |
| Price grid, size | Not given in Hyperliquid's docs for outcomes. The default grid (0.001 to 0.999 in steps of 0.00001) is from [Galaxy](https://www.galaxy.com/insights/research/hyperliquid-hip-4-prediction-markets-polymarket-kalshi-analysis) and [Chainstack](https://docs.chainstack.com/docs/hyperliquid-hip4-outcome-markets-trading); set the grid and `size_step` from the market's metadata | |

## Fees

From [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), "Outcome tokens":

* "Outcome trading only charges fees when closing or settling, not when opening outcome positions."
* "Outcome trading does not support rebates." "Users who would receive rebates for spot and perp trading pay zero fees on maker orders."
* The fee-paying volume is `fee_paying_px * sz`.

From [HIP-4 deployer actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions) (marked "Testnet-only"): users "pay the base outcome trading fee rate times `scale + max(scale, 1)`". Scale 0 gives 1x, 0.5 gives 1.5x, 1 gives 2x, 3 gives 6x.

```python
HIP4Profile(taker_rate=..., maker_rate=..., deployer_scale="1.0")
```

The [HIP-4 page](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets) says "Fees are currently zero for outcome markets for initial testing", so the default rates are 0.

Not published, so chosen by PredictSim:

* The base outcome rate. Hyperliquid gives no number; pass your own.
* Rounding: fees round up to a whole micro-dollar.
* Settlement fee: the taker rate on the settlement value (`settle_fraction × sz` for YES, `(1 − settle_fraction) × sz` for NO).
* `referral_discount` multiplies the rate by `1 − discount`. Hyperliquid's fees page has referral discounts but does not say whether they apply to outcomes or how large they are.

Checked examples: taker 0.0006, 4% referral discount, scale 1.0 → 0.001152 of px × sz (the PRD's case); an opening buy pays 0.

## Recurring BTC binaries

YES wins when the mark price, linearly interpolated between the HyperCore mark updates just before and after settlement time, is at or above the target ([Chainstack](https://docs.chainstack.com/docs/hyperliquid-hip4-outcome-markets-trading)):

```
markPrice0 + (settlementTime - t0) / (t1 - t0) × (markPrice1 - markPrice0) >= targetPrice
```

`predictsim.venues.hip4.btc_binary_settles_yes(mark0, t0, mark1, t1, settlement_time, target)` evaluates this exactly.

## Opening auction

Galaxy reports each HIP-4 market opens with a roughly 15-minute single-price auction; Hyperliquid's docs do not mention it. PredictSim does not model it: start your event stream at continuous trading.
