"""The simulated venue: order validation, taker walk and maker fills.

* A marketable order walks the replayed book from the best price, level by
  level, up to its limit. Size it takes is removed from a shadow of the book
  until the next update for that level, so the same size cannot be taken
  twice. Replayed data is never altered by simulated orders (no market
  impact beyond that).
* A resting order fills from trades at its price once the queue ahead of it
  has drained, and fills in full at its own price if the opposite best price
  reaches or crosses it.
"""

from __future__ import annotations

from collections.abc import Callable

from predictsim.account import Account
from predictsim.book import OrderBook
from predictsim.events import BookSide, Delta, Event, GridChange, Settle, Side, Snapshot, Trade
from predictsim.orders import Fill, Order, OrderStatus, OrderType, Outcome, outcome_px, to_yes
from predictsim.queue import QueueModel, on_level_change, on_trade
from predictsim.spec import Grid, MarketSpec
from predictsim.units import CENTIS_PER_CONTRACT, ONE_DOLLAR

Key = tuple[BookSide, int]


class Exchange:
    """One market on the simulated venue."""

    def __init__(
        self,
        spec: MarketSpec,
        account: Account,
        queue_model: QueueModel,
        on_fill: Callable[[Fill], None],
        strict: bool = True,
    ) -> None:
        self.spec = spec
        self.grid: Grid = spec.grid
        self.account = account
        self.queue_model = queue_model
        self.on_fill = on_fill
        self.book = OrderBook(self.price_ok, strict)
        self.orders: dict[int, Order] = {}
        self.open: dict[int, Order] = {}
        self.resting: dict[Key, list[Order]] = {}
        self.consumed: dict[Key, int] = {}
        self.traded: dict[Key, int] = {}
        self._valid: dict[int, bool] = {}  # price_ok results for the current grid
        self.closed = False
        self.settlement: tuple[int, int, int] | None = None  # (ts, payout, fees)
        self._next_id = 1

    def price_ok(self, px: int) -> bool:
        ok = self._valid.get(px)
        if ok is None:
            ok = self._valid[px] = self.spec.venue.price_ok(self.grid, px)
        return ok

    # ---- order entry ---------------------------------------------------
    def new_order(
        self, ts: int, outcome: Outcome, side: Side, px: int | None, size: int, order_type: OrderType
    ) -> Order:
        """Validate and reserve collateral. Returns the order, PENDING or REJECTED."""
        if order_type is OrderType.MARKET:
            buys_yes = (outcome is Outcome.YES) == (side is Side.BUY)
            yes_px = self.grid.highest() if buys_yes else self.grid.lowest()
            px = outcome_px(outcome, yes_px)
        if px is None:
            raise ValueError("limit orders need a price")
        yes_side, yes_px = to_yes(outcome, side, px)
        order = Order(self._next_id, ts, outcome, side, px, size, order_type, yes_side, yes_px)
        self._next_id += 1
        self.orders[order.order_id] = order
        reason = self._invalid(order)
        if reason is None:
            reason = self.account.reserve(order)
        if reason is not None:
            self._finish(order, ts, OrderStatus.REJECTED, reason)
        else:
            self.open[order.order_id] = order
        return order

    def _invalid(self, o: Order) -> str | None:
        if self.closed:
            return "market closed"
        if o.ts < self.spec.open_ts:
            return "market not open"
        if not self.spec.venue.size_ok(self.spec, o.size):
            return f"size {o.size} is not on the size step"
        if o.size < self.spec.min_size:
            return f"size {o.size} is below the minimum {self.spec.min_size}"
        if not 0 < o.px < ONE_DOLLAR or not self.price_ok(o.yes_px):
            return f"price {o.px} is off the grid"
        if (o.px * o.size) % CENTIS_PER_CONTRACT:
            return "price x size is not a whole micro-dollar"
        value = o.px * o.size // CENTIS_PER_CONTRACT
        if value < self.spec.venue.min_notional:
            return f"order value {value} is below the minimum {self.spec.venue.min_notional}"
        return None

    def _finish(self, o: Order, ts: int, status: OrderStatus, reason: str = "") -> None:
        if o.status is OrderStatus.LIVE:
            level = self.resting[(o.yes_side, o.yes_px)]
            level.remove(o)
            if not level:
                del self.resting[(o.yes_side, o.yes_px)]
        o.status, o.reason, o.done_ts = status, reason, ts
        self.open.pop(o.order_id, None)
        self.account.release(o)

    def arrive(self, order: Order, ts: int) -> None:
        """The order reaches the venue after its submit delay."""
        if order.status is not OrderStatus.PENDING:
            return
        if self.closed:
            return self._finish(order, ts, OrderStatus.CANCELLED, "market closed")
        if not self.price_ok(order.yes_px):
            return self._finish(order, ts, OrderStatus.REJECTED, "price off the grid on arrival")
        available = self._available(order)
        if order.order_type is OrderType.POST_ONLY and available:
            return self._finish(order, ts, OrderStatus.REJECTED, "post-only order would take")
        if order.order_type is OrderType.FOK and available < order.remaining:
            return self._finish(order, ts, OrderStatus.CANCELLED, "fill-or-kill not fillable")
        if available:
            self._walk(order, ts)
        if not order.remaining:
            return
        if order.order_type in (OrderType.GTC, OrderType.POST_ONLY):
            order.status, order.live_ts = OrderStatus.LIVE, ts
            order.queue_ahead = self.book.size_at(order.yes_side, order.yes_px)
            self.resting.setdefault((order.yes_side, order.yes_px), []).append(order)
        else:
            self._finish(order, ts, OrderStatus.CANCELLED, "unfilled remainder cancelled")

    def cancel(self, order: Order, ts: int, reason: str = "cancelled") -> bool:
        """Cancel if still open; False if it already filled or ended."""
        if not order.is_open:
            return False
        self._finish(order, ts, OrderStatus.CANCELLED, reason)
        return True

    def close(self, ts: int) -> None:
        """Market close: cancel every open order and accept no more."""
        for o in list(self.open.values()):
            self.cancel(o, ts, "market closed")
        self.closed = True

    # ---- taker ---------------------------------------------------------
    def _levels(self, o: Order) -> tuple[BookSide, dict[int, int], list[int]]:
        if o.yes_side is BookSide.BID:
            prices = [p for p in self.book.ask_levels() if p <= o.yes_px]
            return BookSide.ASK, self.book.asks, prices
        prices = [p for p in reversed(self.book.bid_levels()) if p >= o.yes_px]
        return BookSide.BID, self.book.bids, prices

    def _available(self, o: Order) -> int:
        side, sizes, prices = self._levels(o)
        return sum(max(sizes[p] - self.consumed.get((side, p), 0), 0) for p in prices)

    def _walk(self, o: Order, ts: int) -> None:
        side, sizes, prices = self._levels(o)
        for p in prices:
            avail = sizes[p] - self.consumed.get((side, p), 0)
            if avail <= 0:
                continue
            take = min(avail, o.remaining)
            self.consumed[(side, p)] = self.consumed.get((side, p), 0) + take
            self._fill(o, ts, p, take, is_maker=False)
            if not o.remaining:
                break

    def _fill(self, o: Order, ts: int, yes_px: int, size: int, is_maker: bool) -> None:
        px = outcome_px(o.outcome, yes_px)
        charge = self.account.fill(o, px, size, is_maker)
        if not o.remaining:
            self._finish(o, ts, OrderStatus.FILLED)
        self.on_fill(Fill(ts, o.order_id, o.outcome, o.side, px, size, is_maker, charge.total))

    # ---- market events -------------------------------------------------
    def on_event(self, ev: Event, index: int) -> bool:
        """Apply one replayed event. Returns False if the book skipped it."""
        if isinstance(ev, Delta):
            return self._on_delta(ev, index)
        if isinstance(ev, Trade):
            self._on_trade(ev)
        elif isinstance(ev, Snapshot):
            return self._on_snapshot(ev, index)
        elif isinstance(ev, GridChange):
            self.grid = Grid(ev.bands)
            self._valid.clear()
        elif isinstance(ev, Settle) and self.settlement is None:
            self.close(ev.ts)
            payout, fees = self.account.settle(ev.settle_fraction)
            self.settlement = (ev.ts, payout, fees)
        return True

    def _on_delta(self, ev: Delta, index: int) -> bool:
        key = (ev.side, ev.px)
        old = self.book.size_at(ev.side, ev.px)
        if not self.book.apply_delta(ev, index):
            return False
        self.consumed.pop(key, None)
        traded = self.traded.pop(key, 0)
        if key in self.resting:
            for o in self.resting[key]:
                o.queue_ahead = on_level_change(self.queue_model, o.queue_ahead, old, ev.new_sz, traded)
        if self.resting:
            self._fill_through(ev.ts)
        return True

    def _on_snapshot(self, ev: Snapshot, index: int) -> bool:
        before = {k: self.book.size_at(*k) for k in self.resting}
        if not self.book.apply_snapshot(ev, index):
            return False
        self.consumed.clear()
        for key, orders in self.resting.items():
            new = self.book.size_at(*key)
            traded = self.traded.get(key, 0)
            for o in orders:
                o.queue_ahead = on_level_change(self.queue_model, o.queue_ahead, before[key], new, traded)
        self.traded.clear()
        if self.resting:
            self._fill_through(ev.ts)
        return True

    def _on_trade(self, ev: Trade) -> None:
        key = (BookSide.BID if ev.aggressor is Side.SELL else BookSide.ASK, ev.px)
        self.traded[key] = self.traded.get(key, 0) + ev.sz
        orders = self.resting.get(key)
        if not orders:
            return
        pool = ev.sz
        for o in list(orders):
            o.queue_ahead, left = on_trade(o.queue_ahead, ev.sz)
            size = min(left, o.remaining, pool)
            if size > 0:
                pool -= size
                self._fill(o, ev.ts, o.yes_px, size, is_maker=True)

    def _fill_through(self, ts: int) -> None:
        bid, ask = self.book.best_bid(), self.book.best_ask()
        for (side, px), orders in list(self.resting.items()):
            through = (side is BookSide.BID and ask is not None and ask <= px) or (
                side is BookSide.ASK and bid is not None and bid >= px
            )
            if through:
                for o in list(orders):
                    self._fill(o, ts, px, o.remaining, is_maker=True)
