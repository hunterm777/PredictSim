"""DataFrame export for pandas and polars."""

from __future__ import annotations

import pandas as pd
import polars as pl
import pytest

from predictsim import BacktestConfig, param_grid, run_backtest, run_many, run_portfolio, run_sweep
from predictsim.frames import (
    FILL_COLUMNS,
    ORDER_COLUMNS,
    TRIP_COLUMNS,
    equity_frame,
    fills_frame,
    orders_frame,
    sweep_frame,
    trips_frame,
)
from tests.sweep_helpers import BuyAtOrBelow, kalshi_spec, market_events

CFG = BacktestConfig(10**8)


def result():  # type: ignore[no-untyped-def]
    return run_backtest(BuyAtOrBelow(400_000), market_events(), kalshi_spec("a"), CFG)


@pytest.mark.parametrize("backend", ["pandas", "polars"])
def test_tables(backend: str) -> None:
    res = result()
    fills, orders, trips = fills_frame(res, backend), orders_frame(res, backend), trips_frame(res, backend)
    assert list(fills.columns) == FILL_COLUMNS and len(fills) == 1
    assert list(orders.columns) == ORDER_COLUMNS and len(orders) == 1
    assert list(trips.columns) == TRIP_COLUMNS and len(trips) == 1
    equity = equity_frame(res, backend)
    assert list(equity.columns) == ["ts", "equity_micros"] and len(equity) == len(res.equity)
    lib = pd if backend == "pandas" else pl
    assert isinstance(fills, lib.DataFrame)


def test_values_and_types() -> None:
    fills = fills_frame(result())
    row = fills.iloc[0]
    assert (row.market_id, row.side, row.liquidity, row.px_micros, row.fee_micros) == (
        "a",
        "buy",
        "maker",
        400_000,
        0,
    )
    assert str(fills.px_micros.dtype) == "int64"
    trips = trips_frame(result(), "polars")
    assert trips["pnl_micros"].to_list() == [600_000] and trips["exit"].to_list() == ["settled"]


def test_many_and_portfolio() -> None:
    mk = [(market_events(), kalshi_spec(m)) for m in ("a", "b")]
    many = run_many(BuyAtOrBelow(400_000), mk, CFG)
    assert fills_frame(many).market_id.tolist() == ["a", "b"]
    port = run_portfolio(BuyAtOrBelow(400_000), mk, CFG)
    assert orders_frame(port, "polars")["market_id"].to_list() == ["a", "b"]
    assert equity_frame(port).equity_micros.iloc[-1] == port.final_equity


def test_sweep_frame() -> None:
    sweep = run_sweep(
        BuyAtOrBelow, param_grid({"px": [390_000, 400_000]}), [(market_events(), kalshi_spec("a"))], CFG
    )
    df = sweep_frame(sweep)
    assert list(df.columns[:3]) == ["param_index", "market_id", "px"]
    assert df.net_pnl.tolist() == [0, 600_000]
    assert sweep_frame(sweep, "polars").height == 2


def test_unknown_backend() -> None:
    with pytest.raises(ValueError, match="backend"):
        fills_frame(result(), "arrow")
