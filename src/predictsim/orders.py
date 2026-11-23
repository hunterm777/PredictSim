"""Orders, fills and the NO-to-YES translation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from predictsim.events import BookSide, Side
from predictsim.units import complement


class Outcome(StrEnum):
    YES = "yes"
    NO = "no"


class OrderType(StrEnum):
    """GTC rests; IOC takes what it can and cancels the rest; FOK fills in
    full or not at all; POST_ONLY is rejected if it would take; MARKET is an
    IOC limit at the worst valid price."""

    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    POST_ONLY = "post_only"
    MARKET = "market"


class OrderStatus(StrEnum):
    PENDING = "pending"  # submitted, still travelling to the venue
    LIVE = "live"  # resting on the venue
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


def to_yes(outcome: Outcome, side: Side, px: int) -> tuple[BookSide, int]:
    """YES-space book side and price an order trades against. Buying NO at q
    is selling YES at 1 - q; selling NO at q is buying YES at 1 - q."""
    buys_yes = (outcome is Outcome.YES) == (side is Side.BUY)
    yes_px = px if outcome is Outcome.YES else complement(px)
    return (BookSide.BID if buys_yes else BookSide.ASK), yes_px


def outcome_px(outcome: Outcome, yes_px: int) -> int:
    """Price of ``outcome`` given a YES price."""
    return yes_px if outcome is Outcome.YES else complement(yes_px)


@dataclass(slots=True)
class Order:
    """One order. ``px`` is in the order's own outcome; ``yes_side`` and
    ``yes_px`` are where it sits in the YES book (a BID buys YES)."""

    order_id: int
    ts: int
    outcome: Outcome
    side: Side
    px: int
    size: int
    order_type: OrderType
    yes_side: BookSide
    yes_px: int
    remaining: int = 0
    status: OrderStatus = OrderStatus.PENDING
    reason: str = ""
    live_ts: int | None = None
    done_ts: int | None = None
    queue_ahead: int = 0
    reserved_cash: int = 0
    reserved_tokens: dict[Outcome, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.remaining:
            self.remaining = self.size

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.LIVE)

    @property
    def filled(self) -> int:
        return self.size - self.remaining


@dataclass(frozen=True, slots=True)
class Fill:
    """One fill. ``px`` is in the order's outcome; ``fee`` is the net fee in
    micro-dollars charged on this fill."""

    ts: int
    order_id: int
    outcome: Outcome
    side: Side
    px: int
    size: int
    is_maker: bool
    fee: int
