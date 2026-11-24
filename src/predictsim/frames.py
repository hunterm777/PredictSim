"""DataFrame export for pandas (``predictsim[pandas]``) or polars
(``predictsim[polars]``).

Each function takes a result and a ``backend`` (``"pandas"`` or
``"polars"``) and returns that library's DataFrame. Money stays in integer
micro-dollars, sizes in centi-contracts and times in nanoseconds, with the
same column names as the CSV exports in :mod:`predictsim.io.csv`.

* :func:`fills_frame`, :func:`orders_frame`, :func:`trips_frame`: one row per
  fill, order or round trip, with a ``market_id`` column.
* :func:`equity_frame`: the equity curve (combined, for many markets or a
  portfolio).
* :func:`sweep_frame`: one row per sweep run, with its parameters and summary.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from predictsim.metrics import BacktestResult, ManyResult
from predictsim.orders import Fill, Order
from predictsim.portfolio import PortfolioResult
from predictsim.sweep import SweepResult
from predictsim.trades import RoundTrip

AnyResult = BacktestResult | ManyResult | PortfolioResult
Columns = dict[str, list[Any]]


def _markets(result: AnyResult) -> list[BacktestResult]:
    if isinstance(result, BacktestResult):
        return [result]
    return result.results if isinstance(result, ManyResult) else result.markets


def _frame(columns: Columns, backend: str) -> Any:
    if backend not in ("pandas", "polars"):
        raise ValueError("backend must be 'pandas' or 'polars'")
    try:
        lib = importlib.import_module(backend)
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(f"install predictsim[{backend}] to export DataFrames") from exc
    return lib.DataFrame(columns)


def _table(names: Sequence[str], rows: Sequence[Sequence[Any]]) -> Columns:
    return {name: [row[i] for row in rows] for i, name in enumerate(names)}


FILL_COLUMNS = ["market_id", "ts", "order_id", "outcome", "side", "px_micros", "size_centis"]
FILL_COLUMNS += ["liquidity", "fee_micros"]
ORDER_COLUMNS = ["market_id", "order_id", "ts", "outcome", "side", "type", "px_micros", "size_centis"]
ORDER_COLUMNS += ["filled_centis", "status", "live_ts", "done_ts", "reason"]
TRIP_COLUMNS = ["market_id", "entry_ts", "exit_ts", "n_fills", "volume_centis", "fees_micros"]
TRIP_COLUMNS += ["pnl_micros", "gross_pnl_micros", "exit"]


def fills_frame(result: AnyResult, backend: str = "pandas") -> Any:
    rows = [_fill_row(r.market_id, f) for r in _markets(result) for f in r.fills]
    return _frame(_table(FILL_COLUMNS, rows), backend)


def orders_frame(result: AnyResult, backend: str = "pandas") -> Any:
    rows = [_order_row(r.market_id, o) for r in _markets(result) for o in r.orders]
    return _frame(_table(ORDER_COLUMNS, rows), backend)


def trips_frame(result: AnyResult, backend: str = "pandas") -> Any:
    rows = [_trip_row(t) for r in _markets(result) for t in r.round_trips]
    return _frame(_table(TRIP_COLUMNS, rows), backend)


def _fill_row(market_id: str, f: Fill) -> list[Any]:
    liquidity = "maker" if f.is_maker else "taker"
    return [market_id, f.ts, f.order_id, str(f.outcome), str(f.side), f.px, f.size, liquidity, f.fee]


def _order_row(market_id: str, o: Order) -> list[Any]:
    head = [market_id, o.order_id, o.ts, str(o.outcome), str(o.side), str(o.order_type), o.px, o.size]
    return [*head, o.filled, str(o.status), o.live_ts, o.done_ts, o.reason]


def _trip_row(t: RoundTrip) -> list[Any]:
    return [t.market_id, t.entry_ts, t.exit_ts, t.n_fills, t.volume, t.fees, t.pnl, t.gross_pnl, t.exit]


def equity_frame(result: AnyResult, backend: str = "pandas") -> Any:
    curve = result.equity
    return _frame({"ts": [t for t, _ in curve], "equity_micros": [v for _, v in curve]}, backend)


def sweep_frame(sweep: SweepResult, backend: str = "pandas") -> Any:
    """One row per run: ``param_index``, ``market_id``, each parameter, then
    every :class:`~predictsim.metrics.Summary` field of that run."""
    rows: list[Mapping[str, Any]] = []
    for run in sweep.runs:
        row: dict[str, Any] = {
            "param_index": run.param_index,
            "market_id": sweep.market_ids[run.market_index],
        }
        row.update(run.params)
        row.update(asdict(run.result.summary()))
        rows.append(row)
    names = list(dict.fromkeys(k for row in rows for k in row))
    return _frame({n: [row.get(n) for row in rows] for n in names}, backend)
