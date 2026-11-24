"""The event loop for one market.

Ordering rule (deterministic): before a replayed event at time T is applied,
every internal action due at or before T runs first, in the order it was
scheduled (order arrivals, cancels, timers, delayed market data, market
close). Callbacks for an event therefore never see a later event.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable, Iterator
from enum import IntEnum
from typing import TYPE_CHECKING

import numpy as np

from predictsim.account import Account, Wallet
from predictsim.book import OrderBook
from predictsim.config import BacktestConfig
from predictsim.events import Delta, Event, Settle, Side, Snapshot, Trade
from predictsim.latency import Fixed
from predictsim.matching import Exchange
from predictsim.metrics import BacktestResult
from predictsim.orders import Fill, Order, OrderType, Outcome
from predictsim.spec import MarketSpec
from predictsim.strategy import Context, Strategy
from predictsim.trades import TripTracker

if TYPE_CHECKING:
    from predictsim.multi import GroupState


class _Act(IntEnum):
    CLOSE = 0
    ARRIVE = 1
    CANCEL = 2
    TIMER = 3
    DATA = 4


class Engine:
    """Runs one market; :meth:`step` advances one replayed event.

    With ``wallet`` the market draws on that shared wallet (portfolio mode)
    and its own results are on a zero base: equity is this market's PnL."""

    def __init__(
        self,
        strategy: Strategy,
        events: Iterable[Event],
        spec: MarketSpec,
        config: BacktestConfig,
        cash: int | None = None,
        wallet: Wallet | None = None,
    ) -> None:
        self.strategy, self.spec, self.config = strategy, spec, config
        if wallet is None:
            self.initial_cash = config.initial_cash if cash is None else cash
            wallet = Wallet(self.initial_cash)
        else:
            self.initial_cash = 0
        self.rng = np.random.default_rng(config.seed)
        self.account = Account(wallet, spec.venue.position_mode, spec.fee_model())
        self.trips = TripTracker(spec.market_id)
        self.on_record: Callable[[Engine], None] | None = None
        self.on_schedule: Callable[[Engine], None] | None = None
        self.clock: Callable[[], int] | None = None  # portfolio mode: global time
        self.group: GroupState | None = None
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
        if self.on_schedule is not None:
            self.on_schedule(self)

    def next_action_ts(self) -> int | None:
        """Time of the next internal action, or None."""
        return self._heap[0][0] if self._heap else None

    def sync(self) -> None:
        """Portfolio mode: bring this market's clock up to the global time
        when another market's callback acts on it."""
        if self.clock is not None:
            self.now = max(self.now, self.clock())

    def submit(self, outcome: Outcome, side: Side, px: int | None, size: int, kind: OrderType) -> Order:
        if self.clock is not None:  # sync(), inlined on the hot path
            self.now = max(self.now, self.clock())
        order = self.exchange.new_order(self.now, outcome, side, px, size, kind)
        if order.is_open:
            delay = self.config.latency.submit.sample(self.rng)
            self._push(self.now + delay, _Act.ARRIVE, order)
        return order

    def request_cancel(self, order_id: int) -> None:
        if self.clock is not None:
            self.now = max(self.now, self.clock())
        order = self.exchange.orders.get(order_id)
        if order is not None and order.is_open:
            delay = self.config.latency.cancel.sample(self.rng)
            self._push(self.now + delay, _Act.CANCEL, order)

    def set_timer(self, ns: int) -> None:
        if ns < 0:
            raise ValueError("timer delay must be >= 0")
        self.sync()
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
        acct = self.account
        self.trips.update(fill.ts, acct.flow, acct.is_flat, fill.size, fill.fee)
        self._dirty = True
        self.strategy.on_fill(self.ctx, fill)

    def split(self, size: int) -> None:
        self.sync()
        self.account.split(size)
        self.holdings_changed()

    def merge(self, size: int) -> None:
        self.sync()
        self.account.merge(size)
        self.holdings_changed()

    def holdings_changed(self) -> None:
        """Record a change to holdings made outside a fill (split, merge,
        multi-outcome conversion)."""
        self.trips.update(self.now, self.account.flow, self.account.is_flat)
        self._dirty = True
        self._record()

    def advance_to(self, ts: int) -> None:
        """Run internal actions due by ``ts`` and move the clock there,
        without applying any replayed event."""
        self._run_actions(ts)
        self.now = max(self.now, ts)

    def mark_value(self) -> int:
        """Holdings marked at the venue mid (or the last known mid)."""
        book = self.exchange.book
        bid, ask = book.best_bid(), book.best_ask()
        if bid is not None and ask is not None:
            self._mark2 = bid + ask
        if self._mark2 is None:
            return 0
        return self.account.value_at(self._mark2, 2)

    def mark_equity(self) -> int:
        """This market's equity: starting cash plus its own cash flow plus
        holdings marked at the venue mid (or the last known mid)."""
        return self.initial_cash + self.account.flow + self.mark_value()

    def _record(self) -> None:
        acct = self.account
        cash = self.initial_cash + acct.flow
        if cash < self.min_cash:
            self.min_cash = cash
        if self._dirty or not acct.is_flat:
            book = self.exchange.book  # mark_equity(), inlined on the hot path
            bid, ask = book.best_bid(), book.best_ask()
            if bid is not None and ask is not None:
                self._mark2 = bid + ask
            mark2 = self._mark2
            self.equity.append((self.now, cash if mark2 is None else cash + acct.value_at(mark2, 2)))
            self._dirty = False
            if self.on_record is not None:
                self.on_record(self)

    # ---- driving -------------------------------------------------------
    def start(self) -> None:
        self.equity.append((self.now, self.initial_cash))
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
            if self.group is not None:
                assert isinstance(ev, Settle)
                self.group.on_settle(self, ev.settle_fraction)
            self.trips.update(ev.ts, self.account.flow, True, fee=self.exchange.settlement[2], settled=True)
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
        acct = self.account
        return BacktestResult(
            market_id=self.spec.market_id,
            initial_cash=self.initial_cash,
            final_cash=self.initial_cash + acct.flow,
            fills=list(self.fills),
            orders=list(self.exchange.orders.values()),
            equity=list(self.equity),
            min_cash=self.min_cash,
            settlement=self.exchange.settlement,
            round_trips=self.trips.finish(self.now, acct.flow, 0 if acct.is_flat else self.mark_value()),
        )
