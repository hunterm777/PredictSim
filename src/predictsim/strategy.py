"""The Strategy base class and the Context it trades through."""

from __future__ import annotations

from typing import TYPE_CHECKING

from predictsim.book import OrderBook
from predictsim.events import Side, Trade
from predictsim.orders import Fill, Order, OrderType, Outcome

if TYPE_CHECKING:
    from predictsim.backtest import Engine


class Context:
    """What a strategy sees and can do. ``book`` lags the venue by the
    market-data delay; treat it as read-only."""

    __slots__ = ("_engine",)

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def now(self) -> int:
        """Current simulated time in nanoseconds."""
        return self._engine.now

    @property
    def book(self) -> OrderBook:
        return self._engine.strategy_book

    @property
    def cash(self) -> int:
        """Total cash in micro-dollars, including cash reserved for orders."""
        return self._engine.account.cash

    @property
    def available_cash(self) -> int:
        """Cash not reserved by open orders."""
        return self._engine.account.available

    @property
    def positions(self) -> dict[Outcome, int]:
        """Holdings in centi-contracts per outcome."""
        return dict(self._engine.account.holdings)

    @property
    def open_orders(self) -> list[Order]:
        return list(self._engine.exchange.open.values())

    def submit(
        self,
        side: Side,
        size: int,
        px: int | None = None,
        outcome: Outcome = Outcome.YES,
        order_type: OrderType = OrderType.GTC,
    ) -> Order:
        """Send an order; ``px`` is in ``outcome``'s price (omit it for
        MARKET). The returned order is REJECTED if validation fails,
        otherwise PENDING until its submit delay elapses."""
        return self._engine.submit(outcome, side, px, size, order_type)

    def cancel(self, order_id: int) -> None:
        """Request a cancel; it reaches the venue after the cancel delay."""
        self._engine.request_cancel(order_id)

    def cancel_all(self) -> None:
        for o in self.open_orders:
            self._engine.request_cancel(o.order_id)

    def set_timer(self, ns: int) -> None:
        """Call :meth:`Strategy.on_timer` ``ns`` nanoseconds from now."""
        self._engine.set_timer(ns)

    def split(self, size: int) -> None:
        """Tokens mode: turn cash into YES + NO pairs ($1 a pair)."""
        self._engine.account.split(size)

    def merge(self, size: int) -> None:
        """Tokens mode: turn YES + NO pairs back into cash."""
        self._engine.account.merge(size)


class Strategy:
    """Override any of these hooks. All are no-ops by default."""

    def on_start(self, ctx: Context) -> None: ...

    def on_book(self, ctx: Context, book: OrderBook) -> None: ...

    def on_trade(self, ctx: Context, trade: Trade) -> None: ...

    def on_fill(self, ctx: Context, fill: Fill) -> None: ...

    def on_timer(self, ctx: Context) -> None: ...

    def on_end(self, ctx: Context) -> None: ...
