"""M5: the Gymnasium environment."""

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from predictsim import BacktestConfig, KalshiProfile, MarketSpec, uniform_grid
from predictsim.env import BUY_ASK, HOLD, SELL_BID, PredictSimEnv
from predictsim.io.csv import load_csv
from tests.conftest import FIXTURES

SPEC = MarketSpec("sample", KalshiProfile(), 0, 30_000, uniform_grid(10_000), 1, 1)
EVENTS = load_csv(FIXTURES / "sample_market.csv")
CFG = BacktestConfig(initial_cash=100_000_000)


def env(**kw: object) -> PredictSimEnv:
    return PredictSimEnv(EVENTS, SPEC, CFG, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize("kw", [{}, {"action_mode": "box"}, {"step_ns": 2_500}])
def test_passes_check_env(kw: dict[str, object]) -> None:
    check_env(env(**kw), skip_render_check=True)


def test_discrete_episode_rewards_sum_to_pnl() -> None:
    e = env(k=2, order_size=300)
    obs, _ = e.reset(seed=1)
    assert obs.shape == (11,) and obs[0] == pytest.approx(0.40) and obs[2] == pytest.approx(0.42)
    obs, r, term, _trunc, info = e.step(BUY_ASK)
    assert obs[-3] == pytest.approx(3.0)
    total, done = r, term
    while not done:
        _, r, done, _, info = e.step(HOLD)
        total += r
    # bought 3 @ 0.42 (fee 0.051156, balance rounded to -1.32), market settled YES
    assert total == pytest.approx(3 - 1.26 - 0.06)
    assert info["equity_micros"] == 100_000_000 - 1_260_000 - 60_000 + 3_000_000
    _, r, done, _, _ = e.step(SELL_BID)  # stepping after the end is a no-op
    assert done and r == 0


def test_box_actions_and_time_steps() -> None:
    e = env(action_mode="box", step_ns=4_000)
    e.reset(seed=0)
    obs, _, _, _, _ = e.step(np.array([0.40, 2.0]))
    assert obs[-1] < 30.0
    e.step(np.array([0.99, -1.0]))
    e.step(np.array([0.5, 0.0]))
    steps = 3
    done = False
    while not done:
        _, _, done, _, _ = e.step(np.array([0.0, 0.0]))
        steps += 1
    assert steps < len(EVENTS)


def test_guards() -> None:
    with pytest.raises(ValueError):
        env(action_mode="other")
    with pytest.raises(RuntimeError):
        env().step(HOLD)
