"""Multi-outcome groups: Polymarket neg-risk convert, HIP-4 negate and
merge-question, and the venues' settlement rules."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from predictsim import (
    BacktestConfig,
    Context,
    Event,
    HIP4Profile,
    HIP4Question,
    KalshiProfile,
    MarketSpec,
    NegRiskEvent,
    Outcome,
    PolymarketProfile,
    Settle,
    Side,
    Snapshot,
    Strategy,
    run_backtest,
    run_portfolio,
    uniform_grid,
)
from predictsim.venues import VenueProfile

CASH = 10_000_000
BOOK = Snapshot(10, ((400_000, 10_000),), ((420_000, 10_000),))


def spec(market_id: str, venue: VenueProfile) -> MarketSpec:
    return MarketSpec(market_id, venue, 0, 1_000, uniform_grid(10_000), 1, 1)


def poly(market_id: str) -> MarketSpec:
    return spec(market_id, PolymarketProfile(fee_rate=0))


def hip4(market_id: str) -> MarketSpec:
    return spec(market_id, HIP4Profile())


def events(settle: int | None) -> list[Event]:
    out: list[Event] = [BOOK]
    if settle is not None:
        out.append(Settle(900, settle))
    return out


class OnStart(Strategy):
    """Run ``action`` once, in the first market's ``on_start``."""

    def __init__(self, action: Callable[[Context], None], market: str = "a") -> None:
        self.action, self.market = action, market
        self.seen: dict[str, dict[Outcome, int]] = {}

    def on_start(self, ctx: Context) -> None:
        if ctx.market_id == self.market:
            self.action(ctx)

    def on_end(self, ctx: Context) -> None:
        self.seen[ctx.market_id] = ctx.positions


def held(port_strategy: OnStart) -> dict[str, tuple[int, int]]:
    return {m: (p[Outcome.YES], p[Outcome.NO]) for m, p in port_strategy.seen.items()}


def test_neg_risk_convert_gives_yes_in_every_other_market() -> None:
    def act(ctx: Context) -> None:
        ctx.split(300)  # $3 into 3 YES + 3 NO of market a
        ctx.convert(200)

    strat = OnStart(act)
    markets = [(events(None), poly(m)) for m in ("a", "b", "c")]
    port = run_portfolio(strat, markets, BacktestConfig(CASH), [NegRiskEvent(("a", "b", "c"))])
    assert held(strat) == {"a": (300, 100), "b": (200, 0), "c": (200, 0)}
    assert port.final_cash == CASH - 3_000_000
    assert [t.exit for t in port.round_trips] == ["open", "open", "open"]


def test_neg_risk_settles_one_winner_and_value_is_kept() -> None:
    def act(ctx: Context) -> None:
        ctx.split(100)
        ctx.convert(100)  # 1 NO of a is worth exactly 1 YES of b + 1 YES of c

    strat = OnStart(act)
    markets = [(events(0), poly("a")), (events(1_000_000), poly("b")), (events(0), poly("c"))]
    port = run_portfolio(strat, markets, BacktestConfig(CASH), [NegRiskEvent(("a", "b", "c"))])
    assert port.final_cash == CASH  # paid $1 to split, b's YES pays $1
    assert [r.settlement for r in port.markets] == [(900, 0, 0), (900, 1_000_000, 0), (900, 0, 0)]
    assert [t.exit for t in port.round_trips] == ["settled", "settled", "settled"]


def test_hip4_negate_and_merge_question() -> None:
    def act(ctx: Context) -> None:
        ctx.split(100)  # 1 YES + 1 NO of x
        ctx.negate(100)  # NO of x -> YES of y and of the fallback
        ctx.merge_question(100)  # YES of x, y, fallback -> $1, credited to x

    strat = OnStart(act, "x")
    markets = [(events(None), hip4(m)) for m in ("x", "y", "other")]
    port = run_portfolio(strat, markets, BacktestConfig(CASH), [HIP4Question(("x", "y"), "other")])
    assert held(strat) == {"x": (0, 0), "y": (0, 0), "other": (0, 0)}
    assert port.final_cash == CASH
    assert [r.final_cash for r in port.markets] == [0, 0, 0]  # -$1 split, +$1 merge, both on x
    assert [t.exit for t in port.round_trips] == ["flat", "flat", "flat"]


def test_hip4_question_settles_when_the_fallback_wins() -> None:
    markets = [(events(0), hip4("x")), (events(0), hip4("y")), (events(1_000_000), hip4("other"))]
    port = run_portfolio(Strategy(), markets, BacktestConfig(CASH), [HIP4Question(("x", "y"), "other")])
    assert port.net_pnl == 0


def run_group(
    markets: list[tuple[list[Event], MarketSpec]], group: object, strat: Strategy | None = None
) -> None:
    run_portfolio(strat or Strategy(), markets, BacktestConfig(CASH), [group])  # type: ignore[list-item]


@pytest.mark.parametrize(
    ("settles", "match"),
    [
        ((500_000, 500_000), "exactly 0 or 1"),
        ((1_000_000, 1_000_000), "second outcome"),
        ((0, 0), "no outcome"),
    ],
)
def test_group_settlement_rules(settles: tuple[int, int], match: str) -> None:
    markets = [(events(s), poly(m)) for s, m in zip(settles, ("a", "b"), strict=True)]
    with pytest.raises(ValueError, match=match):
        run_group(markets, NegRiskEvent(("a", "b")))


def test_unsettled_group_is_not_checked() -> None:
    run_group([(events(0), poly("a")), (events(None), poly("b"))], NegRiskEvent(("a", "b")))


@pytest.mark.parametrize(
    ("action", "match"),
    [
        (lambda ctx: ctx.convert(100), "not enough free no tokens"),
        (lambda ctx: ctx.convert(0), "positive"),
        (lambda ctx: ctx.negate(100), "not available on a NegRiskEvent"),
        (lambda ctx: ctx.merge_question(100), "not available on a NegRiskEvent"),
    ],
)
def test_bad_neg_risk_conversions(action: Callable[[Context], None], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        run_group([(events(None), poly(m)) for m in ("a", "b")], NegRiskEvent(("a", "b")), OnStart(action))


def test_bad_hip4_conversions() -> None:
    markets = [(events(None), hip4(m)) for m in ("a", "b", "f")]
    question = HIP4Question(("a", "b"), "f")
    with pytest.raises(ValueError, match="not available on a HIP4Question"):
        run_group(markets, question, OnStart(lambda ctx: ctx.convert(100)))
    with pytest.raises(ValueError, match="free YES tokens on every outcome"):
        run_group(markets, question, OnStart(lambda ctx: (ctx.split(100), ctx.merge_question(100))))


class ConvertAfterSettle(Strategy):
    def on_end(self, ctx: Context) -> None:
        if ctx.market_id == "b":
            ctx.convert(100)


def test_no_conversion_after_an_outcome_settles() -> None:
    markets = [(events(1_000_000), poly("a")), (events(None), poly("b"))]
    with pytest.raises(ValueError, match="has settled"):
        run_group(markets, NegRiskEvent(("a", "b")), ConvertAfterSettle())


def test_conversion_outside_a_group_is_refused() -> None:
    with pytest.raises(ValueError, match="not in a multi-outcome group"):
        run_backtest(OnStart(lambda ctx: ctx.convert(1), "m"), events(None), poly("m"), BacktestConfig(CASH))


@pytest.mark.parametrize(
    ("markets", "groups", "match"),
    [
        ([poly("a"), poly("b")], [NegRiskEvent(("a",))], "two or more"),
        ([poly("a"), poly("b")], [NegRiskEvent(("a", "a"))], "two or more"),
        ([poly("a"), poly("b")], [NegRiskEvent(("a", "z"))], "not in the portfolio"),
        ([poly("a"), hip4("b")], [NegRiskEvent(("a", "b"))], "not a PolymarketProfile"),
        ([hip4("a"), spec("b", KalshiProfile())], [HIP4Question(("a",), "b")], "not a HIP4Profile"),
        ([poly("a"), poly("b")], [NegRiskEvent(("a", "b")), NegRiskEvent(("b", "a"))], "one group only"),
    ],
)
def test_group_validation(markets: list[MarketSpec], groups: list[object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        run_portfolio(Strategy(), [(events(None), s) for s in markets], BacktestConfig(CASH), groups)  # type: ignore[arg-type]


def test_converted_tokens_can_be_sold() -> None:
    class ConvertThenSell(Strategy):
        def on_start(self, ctx: Context) -> None:
            if ctx.market_id == "a":
                ctx.split(100)
                ctx.convert(100)

        def on_book(self, ctx: Context, book: object) -> None:
            if ctx.market_id == "b" and ctx.positions[Outcome.YES] and not ctx.open_orders:
                ctx.submit(Side.SELL, 100, 400_000)

    port = run_portfolio(
        ConvertThenSell(),
        [(events(None), poly(m)) for m in ("a", "b")],
        BacktestConfig(CASH),
        [NegRiskEvent(("a", "b"))],
    )
    (fill,) = port.markets[1].fills
    assert fill.side is Side.SELL and fill.px == 400_000
