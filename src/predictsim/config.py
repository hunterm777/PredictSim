"""Backtest configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from predictsim.latency import LatencyConfig
from predictsim.queue import QueueModel


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """``initial_cash`` is in micro-dollars."""

    initial_cash: int
    latency: LatencyConfig = field(default_factory=LatencyConfig)
    queue_model: QueueModel = QueueModel.PESSIMISTIC
    seed: int = 0
    strict: bool = True
