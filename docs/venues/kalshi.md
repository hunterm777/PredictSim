# Kalshi

As of November 24, 2026. Implemented in `predictsim.venues.kalshi` and `predictsim.fees.kalshi`.

| Mechanic | Kalshi | Source |
| --- | --- | --- |
| Book | "two arrays of bids: `yes_dollars` for YES positions and `no_dollars` for NO positions". "A NO BID at price Y is equivalent to a YES ASK at price ($1.00 - Y)" | [Orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Orders | One YES book, bid or ask: Create Order V2 uses a "single-book `bid`/`ask` side". Buying NO at q is selling YES at 1 − q | [API docs](https://docs.kalshi.com/llms-full.txt) |
| Positions | One signed position per market: positive is YES, negative is NO (an FCM transfer of 5 NO contracts is `position_centicount` -500), so YES and NO net | [Create FCM Position Transfer](https://docs.kalshi.com/api-reference/fcm/create-fcm-position-transfer) |
| Price grid | Per market, from `price_ranges` bands `{start, end, step}`; whole cents always valid | [Fixed-point migration](https://docs.kalshi.com/getting_started/fixed_point_migration) |
| Size | Fractional contracts, 0.01 granularity | same |

PredictSim keeps a Kalshi account as that one signed number (`Account.position`, in centi-contracts). `ctx.positions` shows it as YES or NO holdings, never both.

## Fees

From [Kalshi's fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) ("Last updated and effective: July 7, 2026"):

* Taker: `round up(M x 0.07 x C x P x (1-P))`, M defaults to 1.
* Maker: `round up(M x 0.0175 x C x P x (1-P))`, M defaults to 0.
* "There is no settlement fee."

M is set per series (`KalshiProfile(taker_multiplier=..., maker_multiplier=...)`) and sits inside the round-up. The [fee schedule page](https://kalshi.com/fee-schedule) lists combos at "maker fees - 50% of taker", which is `maker_multiplier=2`.

Rounding follows [Kalshi's fee rounding page](https://docs.kalshi.com/getting_started/fee_rounding):

1. Trade fee: the model fee rounded up to $0.000001.
2. Balance change `revenue − trade fee` is aligned to $0.01 (non-direct members) or $0.0001 (direct members, `KalshiProfile(direct_member=True)`).
3. Rounding fee: the difference between the two.
4. The accumulator "is maintained per order across all fills regardless of whether the fills are taker or maker". Rounding is rebated "in increments of the user's target balance precision, capped so the fill's net fee cannot be negative".

The fee schedule PDF says the round-up makes "the fee + positionCost ... rounded to a centicent"; the fee rounding page gives the steps above. PredictSim follows the fee rounding page.

Checked examples (in `tests/test_fees_kalshi.py`):

| Case | Result |
| --- | --- |
| Taker, 100 contracts at $0.50 | $1.75 |
| Maker, M = 1, 100 contracts at $0.50 | $0.4375 trade fee + $0.0025 rounding = $0.44 |
| Combo maker, M = 2, 100 contracts at $0.50 | $0.88 |
| Taker, 100 contracts at $0.10 | $0.63 |
| Revenue −$0.055, model fee $0.00363825 | trade fee $0.003639, balance −$0.06, rounding fee $0.001361 |
| Three fills each overpaying $0.004 | $0.01 rebate on the third fill, $0.002 carried |
