# Kalshi

As of November 23, 2026. Implemented in `predictsim.venues.kalshi` and `predictsim.fees.kalshi`.

| Mechanic | Kalshi | Source |
| --- | --- | --- |
| Book | Two bid-only arrays, YES and NO. YES ask = $1.00 − best NO bid | [Orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Price grid | Per market, from `price_ranges` bands `{start, end, step}`; steps from $0.01 down to $0.0001; whole cents always valid | [Fixed-point migration](https://docs.kalshi.com/getting_started/fixed_point_migration) |
| Size | Fractional contracts, 0.01 granularity | same |
| Positions | Net per market | |
| Settlement | $1 or $0 per contract | |

## Fees

Taker fee per fill: `0.07 × M × C × P × (1 − P)`, where C is contracts, P the price and M the market's fee multiplier. Maker fee uses a 0.0175 coefficient, only on series that list maker fees (`KalshiProfile(maker_fees=True)`). The multiplier sits inside the round-up, as in the [CFTC filing](https://cftc.gov/filings/orgrules/rule091222kexdcm003.pdf), which applies `round up(0.035 × C × P × (1 − P))` to INX and NASDAQ-100 markets.

Rounding follows [Kalshi's fee rounding page](https://docs.kalshi.com/getting_started/fee_rounding):

1. Trade fee: the model fee rounded up to $0.000001.
2. Balance change `revenue − trade fee` is floored to $0.01 (non-direct members) or $0.0001 (direct members, `KalshiProfile(direct_member=True)`).
3. Rounding fee: the difference between the two.
4. Each order keeps an accumulator of rounding fees across its fills. Whole multiples of the precision are rebated, capped so the net fee on a fill is never negative.

Every fill records the net fee (trade + rounding − rebate).

Checked examples (in `tests/test_fees_kalshi.py`):

| Case | Result |
| --- | --- |
| Taker, 100 contracts at $0.50 | $1.75 |
| Maker, 100 contracts at $0.50 (maker fees on) | $0.4375 trade fee + $0.0025 rounding = $0.44 |
| Taker, 100 contracts at $0.10 | $0.63 |
| Revenue −$0.055, model fee $0.00363825 | trade fee $0.003639, balance −$0.06, rounding fee $0.001361 |
| Three fills each overpaying $0.004 | $0.01 rebate on the third fill, $0.002 carried |
| Multiplier 0.5 (INX), 100 at $0.50 | $0.88 |
