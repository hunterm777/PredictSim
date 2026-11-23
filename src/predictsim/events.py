"""Market events users supply, all in YES-price space and integer units.

Prices are micro-dollars, sizes centi-contracts, times nanoseconds (UTC).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


class BookSide(StrEnum):
    """Side of the YES book."""

    BID = "bid"
    ASK = "ask"


class Side(StrEnum):
    """Direction of a trade or order."""

    BUY = "buy"
    SELL = "sell"


Level: TypeAlias = tuple[int, int]
"""A book level: (price micros, size centis)."""


@dataclass(frozen=True, slots=True)
class Band:
    """One band of a price grid: valid prices are ``start + k * step`` within
    ``[start, end]``. All values in micro-dollars."""

    start: int
    end: int
    step: int

    def __post_init__(self) -> None:
        if self.step <= 0 or self.start > self.end:
            raise ValueError(f"invalid band {self}")


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Full replace of the book."""

    ts: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]


@dataclass(frozen=True, slots=True)
class Delta:
    """One level set to a new size; ``new_sz == 0`` removes it."""

    ts: int
    side: BookSide
    px: int
    new_sz: int


@dataclass(frozen=True, slots=True)
class Trade:
    """A print on the venue. ``aggressor`` is the taker's side in YES space."""

    ts: int
    px: int
    sz: int
    aggressor: Side


@dataclass(frozen=True, slots=True)
class GridChange:
    """The tick grid changed mid-market."""

    ts: int
    bands: tuple[Band, ...]


@dataclass(frozen=True, slots=True)
class Settle:
    """Market resolved. ``settle_fraction`` is the YES payout in micro-dollars
    per contract: 1_000_000 = YES, 0 = NO, values between are allowed."""

    ts: int
    settle_fraction: int

    def __post_init__(self) -> None:
        if not 0 <= self.settle_fraction <= 1_000_000:
            raise ValueError("settle_fraction must be within [0, 1_000_000]")


Event: TypeAlias = Snapshot | Delta | Trade | GridChange | Settle
BookEvent: TypeAlias = Snapshot | Delta
