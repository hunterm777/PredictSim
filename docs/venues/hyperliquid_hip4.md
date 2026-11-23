# Hyperliquid HIP-4

As of November 23, 2026. Implemented in `predictsim.venues.hip4` and `predictsim.fees.hip4`.

| Mechanic | HIP-4 | Source |
| --- | --- | --- |
| Book | YES and NO tokens with merged books: buy YES at P = sell NO at 1 − P | [Galaxy Research](https://www.galaxy.com/insights/research/hyperliquid-hip-4-prediction-markets-polymarket-kalshi-analysis) |
| Price grid | Bounded 0.001 to 0.999; mainnet quotes up to 5 decimals (default grid: 0.001 to 0.999 in steps of 0.00001) | Galaxy; [Chainstack](https://docs.chainstack.com/docs/hyperliquid-hip4-outcome-markets-trading) |
| Size | Whole shares (the profile rejects fractional sizes) | Chainstack |
| Collateral | USDC | |
| Positions | Separate YES/NO tokens; split and merge | |
| Settlement | YES pays `settleFraction`, NO pays 1 − `settleFraction` | Chainstack |

## Fees

Charged only when closing or settling, never when opening, at the user's spot rate after any referral discount, on `px × sz`. A deployer fee scale of 1.0 charges twice the rate, so the applied rate is `(1 + deployer_scale) × rate × (1 − referral_discount)`. No maker rebates. Source: [Chainstack](https://docs.chainstack.com/docs/hyperliquid-hip4-outcome-markets-trading).

```python
HIP4Profile(taker_rate="0.0006", maker_rate="0.0002", deployer_scale="1.0", referral_discount="0.04")
```

Checked examples: taker rate 0.0006, 4% referral discount, deployer scale 1.0 → 0.001152 of px × sz; an opening buy pays 0.

Not published, so chosen by PredictSim:

* Rounding: fees are rounded up to a whole micro-dollar.
* Settlement fee: the taker rate applied to the settlement value (`settle_fraction × sz` for YES, `(1 − settle_fraction) × sz` for NO).

Galaxy (May 2026) reports outcome fees were zero during initial testing; the default profile rates are 0, so set them explicitly.

## Recurring BTC binaries

YES wins when the mark price, linearly interpolated between the HyperCore mark updates just before and after settlement time, is at or above the target:

```
markPrice0 + (settlementTime - t0) / (t1 - t0) × (markPrice1 - markPrice0) >= targetPrice
```

`predictsim.venues.hip4.btc_binary_settles_yes(mark0, t0, mark1, t1, settlement_time, target)` evaluates this exactly. Recurring daily binaries exist for BTC, ETH, SOL and HYPE, settling at 06:00 UTC.

## Opening auction

Galaxy reports each HIP-4 market opens with a roughly 15-minute single-price clearing auction; Chainstack's guide does not mention it. PredictSim does not model it: start your event stream at continuous trading.
