"""Small builders shared by the matching, queue and account tests."""

from __future__ import annotations

from predictsim.account import Account
from predictsim.events import BookSide, Delta, Snapshot, Trade
from predictsim.matching import Exchange
from predictsim.orders import Fill
from predictsim.queue import QueueModel
from predictsim.spec import MarketSpec, uniform_grid
from predictsim.venues import HIP4Profile, KalshiProfile, VenueProfile

__all__ = ["BookSide", "Delta", "Snapshot", "Trade", "make", "spec_for"]


def spec_for(venue: VenueProfile, close_ts: int = 1_000_000) -> MarketSpec:
    if isinstance(venue, HIP4Profile):
        return MarketSpec("h", venue, 0, close_ts, uniform_grid(10_000), 100, 100)
    return MarketSpec("m", venue, 0, close_ts, uniform_grid(10_000), 1, 1)


def make(
    venue: VenueProfile | None = None,
    cash: int = 100_000_000,
    queue: QueueModel = QueueModel.PESSIMISTIC,
) -> tuple[Exchange, list[Fill]]:
    spec = spec_for(venue or KalshiProfile())
    fills: list[Fill] = []
    acct = Account(cash, spec.venue.position_mode, spec.fee_model())
    return Exchange(spec, acct, queue, fills.append), fills
