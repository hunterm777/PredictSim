"""Latency models: each sample is a whole number of nanoseconds."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


class LatencyModel(Protocol):
    def sample(self, rng: np.random.Generator) -> int:
        """One delay in nanoseconds (>= 0)."""
        ...


@dataclass(frozen=True, slots=True)
class Fixed:
    """A constant delay."""

    ns: int = 0

    def __post_init__(self) -> None:
        if self.ns < 0:
            raise ValueError("latency must be >= 0")

    def sample(self, rng: np.random.Generator) -> int:
        return self.ns


@dataclass(frozen=True, slots=True)
class Uniform:
    """A delay drawn uniformly from the integers in ``[low_ns, high_ns]``."""

    low_ns: int
    high_ns: int

    def __post_init__(self) -> None:
        if not 0 <= self.low_ns <= self.high_ns:
            raise ValueError("need 0 <= low_ns <= high_ns")

    def sample(self, rng: np.random.Generator) -> int:
        return int(rng.integers(self.low_ns, self.high_ns, endpoint=True))


@dataclass(frozen=True, slots=True)
class LogNormal:
    """A lognormal delay with median ``median_ns`` and log-space ``sigma``,
    rounded to the nearest nanosecond."""

    median_ns: int
    sigma: float

    def __post_init__(self) -> None:
        if self.median_ns <= 0 or self.sigma < 0:
            raise ValueError("need median_ns > 0 and sigma >= 0")

    def sample(self, rng: np.random.Generator) -> int:
        return round(float(rng.lognormal(math.log(self.median_ns), self.sigma)))


@dataclass(frozen=True, slots=True)
class LatencyConfig:
    """Delays for order submit, cancel and market data."""

    submit: LatencyModel = field(default_factory=Fixed)
    cancel: LatencyModel = field(default_factory=Fixed)
    data: LatencyModel = field(default_factory=Fixed)
