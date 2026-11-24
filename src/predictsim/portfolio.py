"""Portfolio mode: many markets replayed together on one shared cash balance.

Every market keeps its own book, positions, fees and strategy context, but
all of them draw on one :class:`~predictsim.account.Wallet`, so an order in
one market is checked against cash that orders in the others may already
have reserved, and a payout in one is cash for the next.

Ordering rule (deterministic): the markets' events and internal actions run
in one global time order. At the same timestamp, market starts run first,
then internal actions (order arrivals, cancels, timers, delayed data, close),
then replayed events, then end-of-market work; ties go to the market listed
first. Within a market the single-market rule of
:class:`predictsim.engine.Engine` holds unchanged.

Each market's engine is seeded from ``(config.seed, index)``. Per-market
results are on a zero base (equity is that market's PnL); the combined
equity curve starts at ``config.initial_cash``.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from predictsim.account import Wallet
from predictsim.config import BacktestConfig
from predictsim.engine import Engine
from predictsim.events import Event
from predictsim.metrics import BacktestResult, Summary, _summarize
from predictsim.multi import GroupState, OutcomeGroup
from predictsim.spec import MarketSpec
from predictsim.stats import Performance, TradeStats, performance, trade_stats
from predictsim.strategy import Strategy
from predictsim.trades import RoundTrip

START, ACTION, EVENT, FINISH = 0, 1, 2, 3

StrategySource = Strategy | Callable[[MarketSpec], Strategy]


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    """A portfolio run: the combined equity curve of the shared account and
    one zero-based :class:`BacktestResult` per market, in input order."""

    initial_cash: int
    final_cash: int
    equity: list[tuple[int, int]]
    min_cash: int
    markets: list[BacktestResult]

    @property
    def final_equity(self) -> int:
        return self.equity[-1][1]

    @property
    def net_pnl(self) -> int:
        return self.final_equity - self.initial_cash

    @property
    def total_fees(self) -> int:
        return sum(r.total_fees for r in self.markets)

    @property
    def round_trips(self) -> list[RoundTrip]:
        return [t for r in self.markets for t in r.round_trips]

    def summary(self) -> Summary:
        """Drawdown and return on capital come from the shared account."""
        return _summarize(self.markets, self.equity, self.initial_cash - self.min_cash)

    def breakdown(self) -> dict[str, Summary]:
        """Per-market summaries keyed by market id."""
        return {r.market_id: r.summary() for r in self.markets}

    def performance(
        self, period_ns: int, periods_per_year: float | None = None, risk_free: float = 0.0
    ) -> Performance:
        """Sharpe and Sortino of the combined equity curve."""
        return performance(self.equity, period_ns, periods_per_year, risk_free)

    def trade_stats(self) -> TradeStats:
        return trade_stats(self.round_trips)


def market_seed(seed: int, index: int) -> int:
    """The seed of market ``index`` in a portfolio seeded with ``seed``."""
    return int(np.random.SeedSequence((seed, index)).generate_state(1)[0])


class _Portfolio:
    def __init__(
        self,
        strategy: StrategySource,
        markets: Sequence[tuple[Iterable[Event], MarketSpec]],
        config: BacktestConfig,
        groups: Sequence[OutcomeGroup],
    ) -> None:
        ids = [spec.market_id for _, spec in markets]
        if len(set(ids)) != len(ids):
            raise ValueError("market ids in a portfolio must be unique")
        self.wallet = Wallet(config.initial_cash)
        self.engines: list[Engine] = []
        for i, (events, spec) in enumerate(markets):
            strat = strategy if isinstance(strategy, Strategy) else strategy(spec)
            cfg = replace(config, seed=market_seed(config.seed, i))
            engine = Engine(strat, events, spec, cfg, wallet=self.wallet)
            engine.on_record, engine.on_schedule, engine.clock = self._recorded, self._scheduled, self._now
            self.engines.append(engine)
        self.index = {e: i for i, e in enumerate(self.engines)}
        self.groups = [self._bind(g, ids) for g in groups]
        self.initial = config.initial_cash
        self.last = [0] * len(self.engines)
        self.total = 0
        self.equity: list[tuple[int, int]] = []
        self.min_cash = self.initial
        self.heap: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, int]] = [(e.spec.open_ts, START) for e in self.engines]
        self.active = -1

    def _bind(self, group: OutcomeGroup, ids: list[str]) -> GroupState:
        missing = [m for m in group.market_ids if m not in ids]
        if missing:
            raise ValueError(f"group markets not in the portfolio: {missing}")
        members = [self.engines[ids.index(m)] for m in group.market_ids]
        if any(e.group is not None for e in members):
            raise ValueError("a market can belong to one group only")
        state = GroupState(group, members)
        for e in members:
            e.group = state
        return state

    # ---- callbacks from engines ------------------------------------------
    def _now(self) -> int:
        """Global time: the clock of the market being processed."""
        return self.engines[self.active].now if self.active >= 0 else 0

    def _recorded(self, engine: Engine) -> None:
        i = self.index[engine]
        value = engine.equity[-1][1]
        self.total += value - self.last[i]
        self.last[i] = value
        self.min_cash = min(self.min_cash, self.wallet.cash)
        self.equity.append((engine.now, self.initial + self.total))

    def _scheduled(self, engine: Engine) -> None:
        """An engine scheduled an action; register it if it is now that
        engine's earliest work (the active engine re-registers itself)."""
        i = self.index[engine]
        if i == self.active:
            return
        key = self._key(engine)
        if key < self.keys[i]:
            self.keys[i] = key
            heapq.heappush(self.heap, (*key, i))

    # ---- the global loop --------------------------------------------------
    @staticmethod
    def _key(e: Engine) -> tuple[int, int]:
        """(time, kind) of an engine's next piece of work."""
        nxt, act = e.peek_ts(), e.next_action_ts()
        if nxt is None:
            end = max(e.spec.close_ts, e.now)
            return (act, ACTION) if act is not None and act <= end else (end, FINISH)
        return (act, ACTION) if act is not None and act <= nxt else (nxt, EVENT)

    def run(self) -> PortfolioResult:
        self.equity.append((min((k[0] for k in self.keys), default=0), self.initial))
        for i, key in enumerate(self.keys):
            heapq.heappush(self.heap, (*key, i))
        started = [False] * len(self.engines)
        heap = self.heap
        while heap:
            ts, kind, i = heapq.heappop(heap)
            e = self.engines[i]
            if e.done or (ts, kind) != self.keys[i]:
                continue  # superseded entry
            self.active = i
            if kind == START and not started[i]:
                started[i] = True
                e.start()
            elif kind == ACTION:
                e.advance_to(ts)
            elif kind == EVENT:
                e.step()
            else:
                e.finish()
            self.active = -1
            if not e.done:
                self.keys[i] = self._key(e)
                heapq.heappush(heap, (*self.keys[i], i))
        for g in self.groups:
            g.check_final()
        return PortfolioResult(
            initial_cash=self.initial,
            final_cash=self.wallet.cash,
            equity=self.equity,
            min_cash=self.min_cash,
            markets=[e.result() for e in self.engines],
        )


def run_portfolio(
    strategy: StrategySource,
    markets: Iterable[tuple[Iterable[Event], MarketSpec]],
    config: BacktestConfig,
    groups: Sequence[OutcomeGroup] = (),
) -> PortfolioResult:
    """Replay ``markets`` together on one shared cash balance.

    ``strategy`` is either one :class:`Strategy` used for every market (its
    hooks get each market's own context; see ``ctx.market_id``) or a callable
    that makes one strategy per market from its spec. ``groups`` links
    multi-outcome markets; see :mod:`predictsim.multi`."""
    return _Portfolio(strategy, list(markets), config, groups).run()
