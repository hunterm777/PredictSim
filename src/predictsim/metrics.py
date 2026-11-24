"""Backtest results and summary metrics. Money stays in integer
micro-dollars; only ratios are floats."""

from __future__ import annotations

from dataclasses import dataclass, field

from predictsim.orders import Fill, Order
from predictsim.stats import Performance, TradeStats, performance, trade_stats
from predictsim.trades import RoundTrip


@dataclass(frozen=True, slots=True)
class Summary:
    """Summary of one market or many.

    * ``gross_pnl`` is ``net_pnl`` plus every fee paid, settlement fees included.
    * ``maker_share`` is the maker fraction of filled size.
    * ``max_drawdown`` is the largest peak-to-trough fall of the equity curve.
    * ``return_on_capital`` is net PnL over the most cash ever out of the
      account (in positions and fees); None if no cash was ever used.
    * ``win_rate`` is the fraction of markets with positive net PnL.
    """

    net_pnl: int
    gross_pnl: int
    total_fees: int
    n_fills: int
    maker_share: float | None
    max_drawdown: int
    return_on_capital: float | None
    win_rate: float | None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Everything one market run produced. ``equity`` is a list of
    ``(ts, equity)`` points recorded whenever equity could have changed.
    In portfolio mode ``initial_cash`` is 0 and equity is the market's PnL."""

    market_id: str
    initial_cash: int
    final_cash: int
    fills: list[Fill]
    orders: list[Order]
    equity: list[tuple[int, int]]
    min_cash: int
    settlement: tuple[int, int, int] | None
    round_trips: list[RoundTrip] = field(default_factory=list)

    @property
    def final_equity(self) -> int:
        return self.equity[-1][1] if self.equity else self.final_cash

    @property
    def net_pnl(self) -> int:
        return self.final_equity - self.initial_cash

    @property
    def total_fees(self) -> int:
        settle_fees = self.settlement[2] if self.settlement else 0
        return sum(f.fee for f in self.fills) + settle_fees

    def summary(self) -> Summary:
        return _summarize([self])

    def performance(
        self, period_ns: int, periods_per_year: float | None = None, risk_free: float = 0.0
    ) -> Performance:
        """Sharpe and Sortino of the equity curve; see :mod:`predictsim.stats`."""
        return performance(self.equity, period_ns, periods_per_year, risk_free)

    def trade_stats(self) -> TradeStats:
        """Per-trade breakdown over :attr:`round_trips`."""
        return trade_stats(self.round_trips)


@dataclass(frozen=True, slots=True)
class ManyResult:
    """Results of :func:`predictsim.backtest.run_many`, one per market."""

    results: list[BacktestResult]

    def summary(self) -> Summary:
        return _summarize(self.results)

    def breakdown(self) -> dict[str, Summary]:
        """Per-market summaries keyed by market id."""
        return {r.market_id: r.summary() for r in self.results}

    @property
    def equity(self) -> list[tuple[int, int]]:
        """The markets' equity curves joined in order into one curve that
        starts at the first market's starting cash."""
        base = self.results[0].initial_cash if self.results else 0
        return [(ts, base + v) for ts, v in _chain([r.equity for r in self.results])]

    @property
    def round_trips(self) -> list[RoundTrip]:
        return [t for r in self.results for t in r.round_trips]

    def performance(
        self, period_ns: int, periods_per_year: float | None = None, risk_free: float = 0.0
    ) -> Performance:
        """Sharpe and Sortino of :attr:`equity`; see :mod:`predictsim.stats`."""
        return performance(self.equity, period_ns, periods_per_year, risk_free)

    def trade_stats(self) -> TradeStats:
        return trade_stats(self.round_trips)


def max_drawdown(equity: list[tuple[int, int]]) -> int:
    peak: int | None = None
    worst = 0
    for _, value in equity:
        if peak is None or value > peak:
            peak = value
        worst = max(worst, peak - value)
    return worst


def _summarize(
    results: list[BacktestResult],
    curve: list[tuple[int, int]] | None = None,
    used: int | None = None,
) -> Summary:
    """Summary of ``results``; portfolio mode passes its own combined
    equity ``curve`` and the most shared cash ever ``used``."""
    fills = [f for r in results for f in r.fills]
    net = sum(r.net_pnl for r in results)
    fees = sum(r.total_fees for r in results)
    size = sum(f.size for f in fills)
    maker = sum(f.size for f in fills if f.is_maker)
    if used is None:
        used = max((r.initial_cash - r.min_cash for r in results), default=0)
    if curve is None:
        curve = _chain([r.equity for r in results])
    return Summary(
        net_pnl=net,
        gross_pnl=net + fees,
        total_fees=fees,
        n_fills=len(fills),
        maker_share=maker / size if size else None,
        max_drawdown=max_drawdown(curve),
        return_on_capital=net / used if used > 0 else None,
        win_rate=sum(r.net_pnl > 0 for r in results) / len(results) if results else None,
    )


def _chain(curves: list[list[tuple[int, int]]]) -> list[tuple[int, int]]:
    """Join per-market equity curves into one PnL path."""
    out: list[tuple[int, int]] = []
    offset = 0
    for curve in curves:
        if not curve:
            continue
        start = curve[0][1]
        out.extend((ts, offset + v - start) for ts, v in curve)
        offset += curve[-1][1] - start
    return out
