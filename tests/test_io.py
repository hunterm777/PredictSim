"""CSV and Parquet loaders, exporters, validation and the CLI."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from predictsim.cli import main
from predictsim.events import Band, BookSide, Delta, GridChange, Settle, Side, Snapshot, Trade
from predictsim.io.csv import SchemaError, events_from_rows, load_csv
from predictsim.io.parquet import load_parquet
from predictsim.io.validate import validate
from predictsim.spec import MarketSpec, uniform_grid
from predictsim.venues import PolymarketProfile
from tests.conftest import FIXTURES

ROWS = [
    {"t": "1", "kind": "snapshot", "side": "bid", "px": "0.40", "sz": "10"},
    {"t": "1", "kind": "snapshot", "side": "no_ask", "px": "0.61", "sz": "2"},
    {"t": "1", "kind": "snapshot", "side": "ask", "px": "0.42", "sz": "1.5"},
    {"t": "2", "kind": "grid", "start": "0.001", "end": "0.1", "step": "0.001"},
    {"t": "2", "kind": "grid", "start": "0.1", "end": "0.9", "step": "0.01"},
    {"t": "3", "kind": "delta", "side": "no_bid", "px": "0.55", "sz": "3"},
    {"t": "4", "kind": "trade", "side": "sell", "px": "0.40", "sz": "1"},
    {"t": "5", "kind": "trade", "side": "no_buy", "px": "0.60", "sz": "1"},
    {"t": "5", "kind": "trade", "side": "no_sell", "px": "0.60", "sz": "1"},
    {"t": "6", "kind": "settle", "settle_fraction": "0.25"},
]
MAP = {"ts": "t", "type": "kind"}


def test_rows_become_events() -> None:
    evs = list(events_from_rows(ROWS, MAP))
    assert evs == [
        Snapshot(1, ((390_000, 200), (400_000, 1000)), ((420_000, 150),)),
        GridChange(2, (Band(1_000, 100_000, 1_000), Band(100_000, 900_000, 10_000))),
        Delta(3, BookSide.ASK, 450_000, 300),
        Trade(4, 400_000, 100, Side.SELL),
        Trade(5, 400_000, 100, Side.SELL),
        Trade(5, 400_000, 100, Side.BUY),
        Settle(6, 250_000),
    ]


@pytest.mark.parametrize(
    "row",
    [
        {"ts": "1", "type": "delta", "side": "middle", "px": "0.4", "sz": "1"},
        {"ts": "1", "type": "trade", "side": "up", "px": "0.4", "sz": "1"},
        {"ts": "1", "type": "nope"},
        {"ts": "1", "type": "delta", "side": "bid", "px": "0.4000001", "sz": "1"},
        {"ts": "1", "type": "snapshot", "side": "bid", "px": "x", "sz": "1"},
    ],
)
def test_bad_rows_name_their_row(row: dict[str, str]) -> None:
    with pytest.raises(SchemaError, match="row"):
        list(events_from_rows([row]))


def test_csv_and_parquet_loaders_agree(tmp_path: Path) -> None:
    evs = load_csv(FIXTURES / "sample_market.csv")
    rows = [dict(r) for r in _csv_rows(FIXTURES / "sample_market.csv")]
    path = tmp_path / "m.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    assert load_parquet(path) == evs
    assert len(evs) == 41 and isinstance(evs[-1], Settle)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def test_validate_reports_every_problem() -> None:
    spec = MarketSpec("v", PolymarketProfile("0.05"), 0, 100, uniform_grid(10_000), 1, 1)
    evs = [
        Snapshot(5, ((400_000, 10),), ((420_000, 10),)),
        Delta(4, BookSide.BID, 405_000, 1),
        Delta(6, BookSide.ASK, 400_000, 1),
        Trade(7, 400_000, 0, Side.SELL),
        GridChange(8, (Band(1_000, 999_000, 1_000),)),
        Delta(9, BookSide.BID, 401_000, 1),
        Settle(10, 1_000_000),
        Delta(11, BookSide.BID, 300_000, 1),
    ]
    issues = validate(evs, spec)
    assert [i.index for i in issues] == [1, 1, 2, 3, 7]
    assert "event 1" in str(issues[0])


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(FIXTURES / "sample_market.csv"), "--venue", "kalshi"]) == 0
    assert "OK: 41 events" in capsys.readouterr().out
    bad = tmp_path / "bad.csv"
    bad.write_text("time,type,side,px,sz\n1,delta,bid,0.405,1\n")
    assert main(["validate", str(bad), "--venue", "polymarket", "--map", "ts=time"]) == 1
    assert "off the grid" in capsys.readouterr().out
    assert main(["validate", str(bad), "--venue", "hip4", "--tick", "0.001", "--map", "ts=time"]) == 0
    assert main(["validate", str(tmp_path / "missing.csv"), "--venue", "kalshi"]) == 2
    rows = _csv_rows(FIXTURES / "sample_market.csv")
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / "m.parquet")
    assert main(["validate", str(tmp_path / "m.parquet"), "--venue", "kalshi"]) == 0
