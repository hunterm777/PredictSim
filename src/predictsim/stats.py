"""Risk-adjusted and per-trade statistics.

Sharpe and Sortino ratios are computed on simple returns of the equity
curve sampled at fixed periods:

* ``r_k = E_k / E_(k-1) - 1``, where ``E_k`` is the last recorded equity at
  or before ``start + k * period_ns`` (the first point if none is earlier).
* Sharpe: ``mean(r - rf) / std(r - rf)``, sample standard deviation (ddof 1).
* Sortino: ``(mean(r) - target) / DD`` with downside deviation
  ``DD = sqrt(mean(min(r - target, 0) ** 2))`` over every period.
* Both are per period; pass ``periods_per_year`` to annualize by
  ``sqrt(periods_per_year)``. Prediction markets differ in trading hours,
  so no year length is assumed.

A ratio is None when it is undefined: fewer than two periods, or zero
deviation. Money stays in integer micro-dollars; only ratios are floats.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from predictsim.trades import RoundTrip

Returns = npt.NDArray[np.float64]


def period_returns(equity: Sequence[tuple[int, int]], period_ns: int, start: int | None = None) -> Returns:
    """Simple returns of ``equity`` (``(ts, equity)`` points in time order)
    sampled every ``period_ns`` from ``start`` (default: the first point)."""
    if period_ns <= 0:
        raise ValueError("period_ns must be positive")
    if not equity:
        return np.zeros(0)
    ts = np.fromiter((t for t, _ in equity), dtype=np.int64, count=len(equity))
    values = np.fromiter((v for _, v in equity), dtype=np.int64, count=len(equity))
    t0 = int(ts[0]) if start is None else start
    n = max(0, -((t0 - int(ts[-1])) // period_ns))
    bounds = t0 + period_ns * np.arange(n + 1, dtype=np.int64)
    idx = np.maximum(np.searchsorted(ts, bounds, side="right") - 1, 0)
    sampled = values[idx]
    if np.any(sampled[:-1] <= 0):
        raise ValueError("returns need positive equity; use a result with starting cash")
    out: Returns = sampled[1:] / sampled[:-1] - 1.0
    return out


def sharpe(returns: Returns, risk_free: float = 0.0, periods_per_year: float | None = None) -> float | None:
    """Sharpe ratio of per-period ``returns`` over per-period ``risk_free``."""
    if len(returns) < 2:
        return None
    excess = returns - risk_free
    sd = float(np.std(excess, ddof=1))
    if sd == 0.0:
        return None
    return _annualize(float(np.mean(excess)) / sd, periods_per_year)


def sortino(returns: Returns, target: float = 0.0, periods_per_year: float | None = None) -> float | None:
    """Sortino ratio of per-period ``returns`` against ``target``."""
    if len(returns) < 2:
        return None
    downside = float(np.sqrt(np.mean(np.minimum(returns - target, 0.0) ** 2)))
    if downside == 0.0:
        return None
    return _annualize((float(np.mean(returns)) - target) / downside, periods_per_year)


def _annualize(ratio: float, periods_per_year: float | None) -> float:
    return ratio if periods_per_year is None else ratio * math.sqrt(periods_per_year)


@dataclass(frozen=True, slots=True)
class Performance:
    """Return statistics of one equity curve at one sampling period."""

    period_ns: int
    n_periods: int
    mean_return: float | None
    volatility: float | None
    sharpe: float | None
    sortino: float | None


def performance(
    equity: Sequence[tuple[int, int]],
    period_ns: int,
    periods_per_year: float | None = None,
    risk_free: float = 0.0,
    start: int | None = None,
) -> Performance:
    """Sharpe, Sortino, mean and volatility (sample std) of period returns.
    Sortino uses ``risk_free`` as its target."""
    r = period_returns(equity, period_ns, start)
    return Performance(
        period_ns=period_ns,
        n_periods=len(r),
        mean_return=float(np.mean(r)) if len(r) else None,
        volatility=float(np.std(r, ddof=1)) if len(r) > 1 else None,
        sharpe=sharpe(r, risk_free, periods_per_year),
        sortino=sortino(r, risk_free, periods_per_year),
    )


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Per-trade breakdown over round trips (money in micro-dollars).

    ``avg_loss`` is negative; ``profit_factor`` is gross winning PnL over
    gross losing PnL (None without a loss). Round trips still open at the
    end are included at their marked value."""

    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float | None
    total_pnl: int
    total_fees: int
    expectancy: float | None
    avg_win: float | None
    avg_loss: float | None
    profit_factor: float | None
    avg_hold_ns: float | None


def trade_stats(trips: Sequence[RoundTrip]) -> TradeStats:
    n = len(trips)
    wins = [t.pnl for t in trips if t.pnl > 0]
    losses = [t.pnl for t in trips if t.pnl < 0]
    total = sum(t.pnl for t in trips)
    return TradeStats(
        n_trades=n,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=len(wins) / n if n else None,
        total_pnl=total,
        total_fees=sum(t.fees for t in trips),
        expectancy=total / n if n else None,
        avg_win=sum(wins) / len(wins) if wins else None,
        avg_loss=sum(losses) / len(losses) if losses else None,
        profit_factor=sum(wins) / -sum(losses) if losses else None,
        avg_hold_ns=sum(t.exit_ts - t.entry_ts for t in trips) / n if n else None,
    )
