"""A random agent in the Gymnasium environment (needs predictsim[gym])."""

from __future__ import annotations

from pathlib import Path

from predictsim import BacktestConfig, KalshiProfile, MarketSpec, uniform_grid
from predictsim.env import PredictSimEnv
from predictsim.io.csv import load_csv

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_market.csv"


def run(seed: int = 7) -> float:
    spec = MarketSpec("sample", KalshiProfile(), 0, 30_000, uniform_grid(10_000), 1, 1)
    env = PredictSimEnv(load_csv(FIXTURE), spec, BacktestConfig(initial_cash=100_000_000))
    env.action_space.seed(seed)
    _, _ = env.reset(seed=seed)
    total, done = 0.0, False
    while not done:
        _, reward, terminated, truncated, _ = env.step(env.action_space.sample())
        total += reward
        done = terminated or truncated
    return total


if __name__ == "__main__":
    print(f"episode reward: {run():.6f} dollars")
