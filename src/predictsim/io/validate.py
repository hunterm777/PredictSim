"""Check an event stream before a backtest runs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from predictsim.book import BookError, OrderBook
from predictsim.events import Delta, Event, GridChange, Settle, Snapshot, Trade
from predictsim.spec import Grid, MarketSpec


@dataclass(frozen=True, slots=True)
class Issue:
    index: int
    message: str

    def __str__(self) -> str:
        return f"event {self.index}: {self.message}"


def validate(events: Iterable[Event], spec: MarketSpec) -> list[Issue]:
    """Return every problem found: time going backwards, prices off the grid,
    negative sizes, crossed books, bad trades and events after settlement."""
    grid = spec.grid
    book = OrderBook(lambda px: spec.venue.price_ok(grid, px), strict=True)
    issues: list[Issue] = []
    last_ts: int | None = None
    settled = False
    for i, ev in enumerate(events):
        if last_ts is not None and ev.ts < last_ts:
            issues.append(Issue(i, f"timestamp {ev.ts} is before {last_ts}"))
        last_ts = ev.ts if last_ts is None else max(last_ts, ev.ts)
        if settled:
            issues.append(Issue(i, "event after settlement"))
        try:
            if isinstance(ev, Snapshot):
                book.apply_snapshot(ev, i)
            elif isinstance(ev, Delta):
                book.apply_delta(ev, i)
        except BookError as exc:
            issues.append(Issue(i, exc.reason))
        if isinstance(ev, Trade) and (ev.sz <= 0 or not spec.venue.price_ok(grid, ev.px)):
            issues.append(Issue(i, f"bad trade at {ev.px} for {ev.sz}"))
        elif isinstance(ev, GridChange):
            grid = Grid(ev.bands)
        elif isinstance(ev, Settle):
            settled = True
    return issues
