"""YES-space limit order book replayed from Snapshot and Delta events."""

from __future__ import annotations

import logging
from bisect import bisect_left, insort
from collections.abc import Callable
from fractions import Fraction

from predictsim.events import BookSide, Delta, Level, Snapshot

log = logging.getLogger("predictsim")


class BookError(ValueError):
    """Invalid book input, naming the offending event index."""

    def __init__(self, index: int, reason: str) -> None:
        super().__init__(f"event {index}: {reason}")
        self.index = index
        self.reason = reason


class OrderBook:
    """Price -> size maps for YES bids and asks.

    ``price_ok`` checks prices against the current grid. With ``strict=True``
    a crossed or off-grid event raises :class:`BookError`; otherwise it is
    logged and skipped, leaving the book unchanged.
    """

    __slots__ = ("_ask_px", "_bid_px", "asks", "bids", "price_ok", "strict")

    def __init__(self, price_ok: Callable[[int], bool] | None = None, strict: bool = True) -> None:
        self.bids: dict[int, int] = {}
        self.asks: dict[int, int] = {}
        self._bid_px: list[int] = []
        self._ask_px: list[int] = []
        self.price_ok = price_ok
        self.strict = strict

    # ---- queries -------------------------------------------------------
    def best_bid(self) -> int | None:
        return self._bid_px[-1] if self._bid_px else None

    def best_ask(self) -> int | None:
        return self._ask_px[0] if self._ask_px else None

    def mid(self) -> Fraction | None:
        """Exact midpoint in micro-dollars, or None if a side is empty."""
        if not self._bid_px or not self._ask_px:
            return None
        return Fraction(self._bid_px[-1] + self._ask_px[0], 2)

    def spread(self) -> int | None:
        if not self._bid_px or not self._ask_px:
            return None
        return self._ask_px[0] - self._bid_px[-1]

    def size_at(self, side: BookSide, px: int) -> int:
        return (self.bids if side is BookSide.BID else self.asks).get(px, 0)

    def depth(self, n: int) -> tuple[list[Level], list[Level]]:
        """Top ``n`` levels per side, best first."""
        bids = [(p, self.bids[p]) for p in reversed(self._bid_px[-n:])] if n > 0 else []
        asks = [(p, self.asks[p]) for p in self._ask_px[:n]]
        return bids, asks

    def ask_levels(self) -> list[int]:
        """Ask prices, best (lowest) first. Do not mutate."""
        return self._ask_px

    def bid_levels(self) -> list[int]:
        """Bid prices, best (highest) last. Do not mutate."""
        return self._bid_px

    def copy(self) -> OrderBook:
        out = OrderBook(self.price_ok, self.strict)
        out.bids, out.asks = dict(self.bids), dict(self.asks)
        out._bid_px, out._ask_px = list(self._bid_px), list(self._ask_px)
        return out

    # ---- updates -------------------------------------------------------
    def _reject(self, index: int, reason: str) -> bool:
        if self.strict:
            raise BookError(index, reason)
        log.warning("skipping event %d: %s", index, reason)
        return False

    def _check_level(self, index: int, px: int, sz: int) -> str | None:
        if sz < 0:
            return f"negative size {sz} at {px}"
        if self.price_ok is not None and sz > 0 and not self.price_ok(px):
            return f"price {px} is off the grid"
        return None

    def apply_snapshot(self, ev: Snapshot, index: int) -> bool:
        """Replace the whole book. Returns False if skipped."""
        for px, sz in (*ev.bids, *ev.asks):
            bad = self._check_level(index, px, sz)
            if bad:
                return self._reject(index, bad)
        bids = {px: sz for px, sz in ev.bids if sz > 0}
        asks = {px: sz for px, sz in ev.asks if sz > 0}
        if bids and asks and max(bids) >= min(asks):
            return self._reject(index, f"crossed snapshot {max(bids)} >= {min(asks)}")
        self.bids, self.asks = bids, asks
        self._bid_px, self._ask_px = sorted(bids), sorted(asks)
        return True

    def apply_delta(self, ev: Delta, index: int) -> bool:
        """Set one level. Returns False if skipped."""
        px, sz = ev.px, ev.new_sz
        bad = self._check_level(index, px, sz)
        if bad:
            return self._reject(index, bad)
        if ev.side is BookSide.BID:
            if sz and self._ask_px and px >= self._ask_px[0]:
                return self._reject(index, f"bid {px} crosses ask {self._ask_px[0]}")
            self._set(self.bids, self._bid_px, px, sz)
        else:
            if sz and self._bid_px and px <= self._bid_px[-1]:
                return self._reject(index, f"ask {px} crosses bid {self._bid_px[-1]}")
            self._set(self.asks, self._ask_px, px, sz)
        return True

    @staticmethod
    def _set(levels: dict[int, int], prices: list[int], px: int, sz: int) -> None:
        if sz:
            if px not in levels:
                insort(prices, px)
            levels[px] = sz
        elif px in levels:
            del levels[px]
            del prices[bisect_left(prices, px)]
