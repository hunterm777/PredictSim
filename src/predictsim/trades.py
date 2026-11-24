"""Round trips: per-trade records for the per-trade breakdown.

A round trip runs from the first change that takes a market's holdings off
flat (a fill, a split or a conversion) until they are flat again, by trading,
merging, converting or settlement. Its PnL is the market's net cash change
over the round trip, so fees and settlement are included exactly. One still
open when the run ends is valued at the last mark and has ``exit == "open"``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """One round trip. Money in micro-dollars, ``volume`` in centi-contracts.

    ``exit`` is ``"flat"`` (traded or merged back to flat), ``"settled"``
    (paid out at settlement) or ``"open"`` (still held at the end, marked)."""

    market_id: str
    entry_ts: int
    exit_ts: int
    n_fills: int
    volume: int
    fees: int
    pnl: int
    exit: str

    @property
    def gross_pnl(self) -> int:
        """PnL before fees."""
        return self.pnl + self.fees


class TripTracker:
    """Builds :class:`RoundTrip` records from one market's flow and holdings."""

    __slots__ = ("_fees", "_flat_flow", "_n", "_open", "_ts", "_volume", "market_id", "trips")

    def __init__(self, market_id: str) -> None:
        self.market_id = market_id
        self.trips: list[RoundTrip] = []
        self._open = False
        self._flat_flow = 0
        self._ts = self._n = self._volume = self._fees = 0

    def update(
        self, ts: int, flow: int, flat: bool, size: int = 0, fee: int = 0, settled: bool = False
    ) -> None:
        """Record a change: ``size`` and ``fee`` of a fill (0 for other changes),
        the market's ``flow`` and whether its holdings are ``flat`` after it."""
        if not self._open:
            if flat:
                self._flat_flow = flow
                return
            self._open, self._ts, self._n, self._volume, self._fees = True, ts, 0, 0, 0
        if size:
            self._n += 1
            self._volume += size
        self._fees += fee
        if flat:
            self._close(ts, flow - self._flat_flow, "settled" if settled else "flat")
            self._flat_flow = flow

    def finish(self, ts: int, flow: int, value: int) -> list[RoundTrip]:
        """Every round trip, with one still open valued at ``value``."""
        trips = list(self.trips)
        if self._open:
            pnl = flow - self._flat_flow + value
            n, vol, fees = self._n, self._volume, self._fees
            trips.append(RoundTrip(self.market_id, self._ts, ts, n, vol, fees, pnl, "open"))
        return trips

    def _close(self, ts: int, pnl: int, exit: str) -> None:
        trip = RoundTrip(self.market_id, self._ts, ts, self._n, self._volume, self._fees, pnl, exit)
        self.trips.append(trip)
        self._open = False
