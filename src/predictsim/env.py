"""Gymnasium environment (needs the ``gym`` extra).

One episode is one market from open to settlement. Observation: the top K
bid and ask levels of the strategy's (lagged) book as (price, size) pairs in
dollars and contracts, then net YES position in contracts, cash in dollars
and seconds to close. Reward: change in mark-to-market equity net of fees,
in dollars; the terminal step includes settlement.

Actions:

* ``"discrete"``: 0 hold, 1 buy YES at the best ask, 2 sell YES at the best
  bid, each ``order_size`` centi-contracts, immediate-or-cancel.
* ``"box"``: ``[limit price in dollars, signed size in contracts]``; each step
  cancels open orders and, if the size is non-zero after snapping to the size
  step, places a GTC limit order (positive buys YES, negative sells YES).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from predictsim.backtest import BacktestConfig, Engine
from predictsim.events import Event, Side
from predictsim.orders import OrderType
from predictsim.spec import MarketSpec
from predictsim.strategy import Strategy
from predictsim.units import CENTIS_PER_CONTRACT, MICROS_PER_DOLLAR, NANOS_PER_SECOND

HOLD, BUY_ASK, SELL_BID = 0, 1, 2


class PredictSimEnv(gym.Env[np.ndarray, Any]):
    metadata: dict[str, Any] = {"render_modes": []}  # noqa: RUF012

    def __init__(
        self,
        events: Sequence[Event],
        spec: MarketSpec,
        config: BacktestConfig,
        k: int = 5,
        order_size: int = 100,
        action_mode: str = "discrete",
        step_ns: int | None = None,
    ) -> None:
        if action_mode not in ("discrete", "box"):
            raise ValueError("action_mode must be 'discrete' or 'box'")
        self.events, self.market, self.config = list(events), spec, config
        self.k, self.order_size, self.action_mode, self.step_ns = k, order_size, action_mode, step_ns
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(4 * k + 3,), dtype=np.float64)
        if action_mode == "discrete":
            self.action_space: spaces.Space[Any] = spaces.Discrete(3)
        else:
            top = order_size / CENTIS_PER_CONTRACT
            self.action_space = spaces.Box(np.array([0.0, -top]), np.array([1.0, top]), dtype=np.float64)
        self._engine: Engine | None = None
        self._equity = 0

    # ---- gym API -------------------------------------------------------
    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        cfg = self.config
        if seed is not None:
            cfg = BacktestConfig(cfg.initial_cash, cfg.latency, cfg.queue_model, seed, cfg.strict)
        self._engine = Engine(Strategy(), self.events, self.market, cfg)
        self._engine.start()
        self._engine.step()
        self._equity = self._mtm()
        return self._obs(), {}

    def step(self, action: Any) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        eng = self._require()
        if not eng.done:
            self._act(action)
            self._advance()
        equity = self._mtm()
        reward = (equity - self._equity) / MICROS_PER_DOLLAR
        self._equity = equity
        terminated = eng.done or eng.exchange.settlement is not None
        if terminated:
            eng.finish()
        return self._obs(), reward, terminated, False, {"equity_micros": equity}

    # ---- internals -----------------------------------------------------
    def _require(self) -> Engine:
        if self._engine is None:
            raise RuntimeError("call reset() first")
        return self._engine

    def _act(self, action: Any) -> None:
        eng = self._require()
        ctx, book = eng.ctx, eng.strategy_book
        if self.action_mode == "discrete":
            a = int(action)
            if a == BUY_ASK and book.best_ask() is not None:
                ctx.submit(Side.BUY, self.order_size, book.best_ask(), order_type=OrderType.IOC)
            elif a == SELL_BID and book.best_bid() is not None:
                ctx.submit(Side.SELL, self.order_size, book.best_bid(), order_type=OrderType.IOC)
            return
        ctx.cancel_all()
        px = eng.exchange.grid.snap_down(round(float(action[0]) * MICROS_PER_DOLLAR))
        signed = round(float(action[1]) * CENTIS_PER_CONTRACT)
        size = abs(signed) - abs(signed) % self.market.size_step
        if px is not None and size >= self.market.min_size:
            ctx.submit(Side.BUY if signed > 0 else Side.SELL, size, px)

    def _advance(self) -> None:
        eng = self._require()
        if self.step_ns is None:
            eng.step()
            return
        target = eng.now + self.step_ns
        while True:
            nxt = eng.peek_ts()
            if nxt is None:
                eng.step()  # finishes the run
                return
            if nxt > target and eng.now < target:
                eng.advance_to(target)
                return
            eng.step()
            if eng.now >= target:
                return

    def _mtm(self) -> int:
        return self._require().mark_equity()

    def _obs(self) -> np.ndarray:
        eng = self._require()
        bids, asks = eng.strategy_book.depth(self.k)
        out = np.zeros(4 * self.k + 3, dtype=np.float64)
        for i, (px, sz) in enumerate(bids):
            out[4 * i], out[4 * i + 1] = px / MICROS_PER_DOLLAR, sz / CENTIS_PER_CONTRACT
        for i, (px, sz) in enumerate(asks):
            out[4 * i + 2], out[4 * i + 3] = px / MICROS_PER_DOLLAR, sz / CENTIS_PER_CONTRACT
        acct = eng.account
        out[-3] = acct.net_yes / CENTIS_PER_CONTRACT
        out[-2] = acct.cash / MICROS_PER_DOLLAR
        out[-1] = max(self.market.close_ts - eng.now, 0) / NANOS_PER_SECOND
        return out
