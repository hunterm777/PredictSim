"""M4 golden test: identical fill logs, byte for byte, on every run.

The golden file was produced by this code and is checked in, so CI on other
machines and Python versions must reproduce it exactly. Regenerate it only
for an intended behaviour change:  python -m tests.test_backtest_golden
"""

from __future__ import annotations

import sys
from pathlib import Path

from predictsim import BacktestConfig, LatencyConfig, LogNormal, QueueModel, Uniform
from predictsim.io.csv import write_equity, write_fills, write_orders
from tests.conftest import FIXTURES

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import fade_the_move
import spread_capture

CONFIG = BacktestConfig(
    initial_cash=100_000_000,
    latency=LatencyConfig(submit=Uniform(0, 300), cancel=Uniform(100, 900), data=LogNormal(200, 0.5)),
    queue_model=QueueModel.PROPORTIONAL,
    seed=42,
)
GOLDEN = FIXTURES / "golden"


def produce(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, module in (("spread_capture", spread_capture), ("fade_the_move", fade_the_move)):
        res = module.run(CONFIG)
        write_fills(out / f"{name}_fills.csv", res.fills)
        write_orders(out / f"{name}_orders.csv", res.orders)
        write_equity(out / f"{name}_equity.csv", res.equity)


def test_three_runs_match_golden_bytes(tmp_path: Path) -> None:
    golden = {p.name: p.read_bytes() for p in sorted(GOLDEN.iterdir())}
    assert len(golden) == 6
    for run in range(3):
        out = tmp_path / str(run)
        produce(out)
        for name, data in golden.items():
            assert (out / name).read_bytes() == data, f"run {run}: {name} differs"


if __name__ == "__main__":
    produce(GOLDEN)
