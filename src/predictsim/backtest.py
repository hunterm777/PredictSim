"""The event loop: run_backtest and run_many.

Ordering rule (deterministic): before a replayed event at time T is applied,
every internal action due at or before T runs first, in the order it was
scheduled (order arrivals, cancels, timers, delayed market data, market
close). Callbacks for an event therefore never see a later event.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np

from predictsim.account import Account
from predictsim.book import OrderBook
from predictsim.events import Delta, Event, Side, Snapshot, Trade
from predictsim.latency import Fixed, LatencyConfig
from predictsim.matching import Exchange
from predictsim.metrics import BacktestResult, ManyResult
from predictsim.orders import Fill, Order, OrderType, Outcome
from predictsim.queue import QueueModel
from predictsim.spec import MarketSpec
from predictsim.strategy import Context, Strategy


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """``initial_cash`` is in micro-dollars."""

    initial_cash: int
    latency: LatencyConfig = field(default_factory=LatencyConfig)
    queue_model: QueueModel = QueueModel.PESSIMISTIC
    seed: int = 0
    strict: bool = True


class _Act(IntEnum):
    CLOSE = 0
    ARRIVE = 1
    CANCEL = 2
    TIMER = 3
    DATA = 4


class Engine:
    """Runs one market; :meth:`step` advances one replayed event."""

    def __init__(
        self,
        strategy: Strategy,
        events: Iterable[Event],
        spec: MarketSpec,
        config: BacktestConfig,
        cash: int | None = None,
    ) -> None:
        self.strategy, self.spec, self.config = strategy, spec, config
        self.initial_cash = config.initial_cash if cash is None else cash
        self.rng = np.random.default_rng(config.seed)
        self.account = Account(self.initial_cash, spec.venue.position_mode, spec.fee_model())
        self.exchange = Exchange(spec, self.account, config.queue_model, self._on_fill, config.strict)
        lat = config.latency
        self._inline_data = isinstance(lat.data, Fixed) and lat.data.ns == 0
        self.strategy_book = self.exchange.book if self._inline_data else OrderBook()
        self.ctx = Context(self)
        self.now = spec.open_ts
        self.fills: list[Fill] = []
        self.equity: list[tuple[int, int]] = []
        self.min_cash = self.initial_cash
        self._events: Iterator[Event] = iter(events)
        self._index = 0
        self._peeked: Event | None = None
        self._last_ts: int | None = None
        self._last_delivery = 0
        self._heap: list[tuple[int, int, _Act, object]] = []
        self._seq = 0
        self._mark2: int | None = None  # best bid + best ask, i.e. twice the mid
        self._dirty = False
        self.done = False
        self._push(spec.close_ts, _Act.CLOSE, None)

    # ---- scheduling ----------------------------------------------------
    def _push(self, ts: int, act: _Act, payload: object) -> None:
        heapq.heappush(self._heap, (ts, self._seq, act, payload))
        self._seq += 1

    def submit(self, outcome: Outcome, side: Side, px: int | None, size: int, kind: OrderType) -> Order:
        order = self.exchange.new_order(self.now, outcome, side, px, size, kind)
        if order.is_open:
            delay = self.config.latency.submit.sample(self.rng)
            self._push(self.now + delay, _Act.ARRIVE, order)
        return order

    def request_cancel(self, order_id: int) -> None:
        order = self.exchange.orders.get(order_id)
        if order is not None and order.is_open:
            delay = self.config.latency.cancel.sample(self.rng)
            self._push(self.now + delay, _Act.CANCEL, order)

    def set_timer(self, ns: int) -> None:
        if ns < 0:
            raise ValueError("timer delay must be >= 0")
        self._push(self.now + ns, _Act.TIMER, None)

    def _run_actions(self, until: int | None, timers: bool = True) -> None:
        heap = self._heap
        while heap and (until is None or heap[0][0] <= until):
            ts, _, act, payload = heapq.heappop(heap)
            if act is _Act.TIMER and not timers:
                continue
            self.now = max(self.now, ts)
            if act is _Act.ARRIVE:
                assert isinstance(payload, Order)
                self.exchange.arrive(payload, self.now)
            elif act is _Act.CANCEL:
                assert isinstance(payload, Order)
                self.exchange.cancel(payload, self.now)
            elif act is _Act.TIMER:
                self.strategy.on_timer(self.ctx)
            elif act is _Act.DATA:
                assert isinstance(payload, tuple)
                self._deliver(*payload)
            else:
                self.exchange.close(self.now)
            if self._dirty:
                self._record()

    # ---- market data ---------------------------------------------------
    def _deliver(self, ev: Snapshot | Delta | Trade, index: int) -> None:
        if isinstance(ev, Trade):
            self.strategy.on_trade(self.ctx, ev)
            return
        if not self._inline_data:
            if isinstance(ev, Snapshot):
                self.strategy_book.apply_snapshot(ev, index)
            else:
                self.strategy_book.apply_delta(ev, index)
        self.strategy.on_book(self.ctx, self.strategy_book)

    def _on_fill(self, fill: Fill) -> None:
        self.fills.append(fill)
        self._dirty = True
        self.strategy.on_fill(self.ctx, fill)

    def advance_to(self, ts: int) -> None:
        """Run internal actions due by ``ts`` and move the clock there,
        without applying any replayed event."""
        self._run_actions(ts)
        self.now = max(self.now, ts)

    def mark_equity(self) -> int:
        """Equity marked at the venue mid (or the last known mid)."""
        book = self.exchange.book
        bid, ask = book.best_bid(), book.best_ask()
        if bid is not None and ask is not None:
            self._mark2 = bid + ask
        if self._mark2 is None:
            return self.account.cash
        return self.account.equity_at(self._mark2, 2)

    def _record(self) -> None:
        acct = self.account
        if acct.cash < self.min_cash:
            self.min_cash = acct.cash
        if self._dirty or not acct.is_flat:
            self.equity.append((self.now, self.mark_equity()))
            self._dirty = False

    # ---- driving -------------------------------------------------------
    def start(self) -> None:
        self.equity.append((self.now, self.account.cash))
        self.strategy.on_start(self.ctx)

    def step(self) -> bool:
        """Apply the next replayed event. Returns False when none are left."""
        ev = self._take()
        if ev is None:
            self.finish()
            return False
        index = self._index
        self._index += 1
        if self._last_ts is not None and ev.ts < self._last_ts:
            raise ValueError(f"event {index}: timestamp {ev.ts} goes backwards")
        self._last_ts = ev.ts
        if self._heap and self._heap[0][0] <= ev.ts:
            self._run_actions(ev.ts)
        self.now = max(self.now, ev.ts)
        settled_before = self.exchange.settlement is not None
        applied = self.exchange.on_event(ev, index)
        if applied and isinstance(ev, (Snapshot, Delta, Trade)):
            if self._inline_data:
                self._deliver(ev, index)
            else:
                lag = self.config.latency.data.sample(self.rng)
                self._last_delivery = max(ev.ts + lag, self._last_delivery)
                self._push(self._last_delivery, _Act.DATA, (ev, index))
        if not settled_before and self.exchange.settlement is not None:
            self._dirty = True
        self._record()
        return True

    def _take(self) -> Event | None:
        if self._peeked is not None:
            ev, self._peeked = self._peeked, None
            return ev
        return next(self._events, None)

    def peek_ts(self) -> int | None:
        """Timestamp of the next replayed event, or None at the end."""
        if self._peeked is None:
            self._peeked = next(self._events, None)
        return None if self._peeked is None else self._peeked.ts

    def finish(self) -> None:
        if self.done:
            return
        self._run_actions(max(self.spec.close_ts, self.now))
        self._run_actions(None, timers=False)
        self.strategy.on_end(self.ctx)
        self._run_actions(None, timers=False)
        self._dirty = True
        self._record()
        self.done = True

    def result(self) -> BacktestResult:
        return BacktestResult(
            market_id=self.spec.market_id,
            initial_cash=self.initial_cash,
            final_cash=self.account.cash,
            fills=list(self.fills),
            orders=list(self.exchange.orders.values()),
            equity=list(self.equity),
            min_cash=self.min_cash,
            settlement=self.exchange.settlement,
        )


def run_backtest(
    strategy: Strategy,
    events: Iterable[Event],
    spec: MarketSpec,
    config: BacktestConfig,
    cash: int | None = None,
) -> BacktestResult:
    """Run one market from open to the end of its events."""
    engine = Engine(strategy, events, spec, config, cash)
    engine.start()
    while engine.step():
        pass
    return engine.result()


def run_many(
    strategy: Strategy,
    markets: Iterable[tuple[Iterable[Event], MarketSpec]],
    config: BacktestConfig,
    carry_cash: bool = True,
) -> ManyResult:
    """Run markets in sequence. With ``carry_cash`` each market starts with
    the previous market's final cash; otherwise each starts with
    ``config.initial_cash``. Positions are never carried between markets."""
    results: list[BacktestResult] = []
    cash = config.initial_cash
    for events, spec in markets:
        res = run_backtest(strategy, events, spec, config, cash if carry_cash else None)
        results.append(res)
        cash = res.final_cash
    return ManyResult(results)
