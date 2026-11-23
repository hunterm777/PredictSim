"""Cash, positions, collateral and settlement. All amounts are integers.

Contracts are fully collateralized: buying YES at P costs P and buying NO
costs 1 - P (the NO price). Cash for the opening part of an order, plus an
upper bound on its fee, is reserved when the order is submitted; an order
that would overdraw available cash is rejected.

Position modes:

* ``net`` (Kalshi): selling an outcome you do not hold buys the other one,
  and buying an outcome while holding the other closes that first.
* ``tokens`` (Polymarket, HIP-4): YES and NO are separate balances. Selling
  needs tokens you hold; :meth:`split` and :meth:`merge` convert cash and
  pairs of tokens at $1 a pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from predictsim.events import Side
from predictsim.fees.base import FeeCharge, FeeInput, FeeModel
from predictsim.orders import Order, Outcome
from predictsim.units import CENTIS_PER_CONTRACT, ONE_DOLLAR, complement, notional
from predictsim.venues.base import PositionMode


def other(outcome: Outcome) -> Outcome:
    return Outcome.NO if outcome is Outcome.YES else Outcome.YES


@dataclass(frozen=True, slots=True)
class Plan:
    """How a buy or sell splits into closing and opening size.

    ``close_outcome`` is the outcome whose holdings shrink; ``open_outcome``
    is the outcome bought with the rest."""

    close_outcome: Outcome
    close: int
    open_outcome: Outcome
    open: int


class Account:
    """Cash and token holdings for one market."""

    def __init__(self, cash: int, mode: PositionMode, fees: FeeModel) -> None:
        if cash < 0:
            raise ValueError("cash must be >= 0")
        self.cash = cash
        self.mode = mode
        self.fees = fees
        self.reserved = 0
        self.holdings: dict[Outcome, int] = {Outcome.YES: 0, Outcome.NO: 0}
        self.reserved_tokens: dict[Outcome, int] = {Outcome.YES: 0, Outcome.NO: 0}

    @property
    def available(self) -> int:
        return self.cash - self.reserved

    def free_tokens(self, outcome: Outcome) -> int:
        return self.holdings[outcome] - self.reserved_tokens[outcome]

    @property
    def net_yes(self) -> int:
        """YES holdings minus NO holdings, in centis."""
        return self.holdings[Outcome.YES] - self.holdings[Outcome.NO]

    # ---- planning and reservation --------------------------------------
    def plan(self, outcome: Outcome, side: Side, size: int) -> Plan | None:
        """Split an order; None if a tokens-mode sell lacks free tokens."""
        if side is Side.SELL:
            free = self.free_tokens(outcome)
            if self.mode is PositionMode.TOKENS:
                return Plan(outcome, size, other(outcome), 0) if free >= size else None
            close = min(size, max(free, 0))
            return Plan(outcome, close, other(outcome), size - close)
        if self.mode is PositionMode.TOKENS:
            return Plan(other(outcome), 0, outcome, size)
        close = min(size, max(self.free_tokens(other(outcome)), 0))
        return Plan(other(outcome), close, outcome, size - close)

    def reserve(self, order: Order, check: bool = True) -> str | None:
        """Reserve cash and tokens for the rest of ``order``; returns a reason
        string if ``check`` is set and there is not enough."""
        plan = self.plan(order.outcome, order.side, order.remaining)
        if plan is None:
            return "not enough tokens to sell"
        open_px = self._open_px(order.outcome, order.side, order.px)
        cost = notional(open_px, plan.open)
        fee = self.fees.quote(self._fee_input(order, order.px, order.remaining, plan, False))
        need = cost + max(fee, 0)
        if check and need > self.available:
            return f"needs {need} micros, {self.available} available"
        order.reserved_cash = need
        order.reserved_tokens = {plan.close_outcome: plan.close} if plan.close else {}
        self.reserved += need
        for o, n in order.reserved_tokens.items():
            self.reserved_tokens[o] += n
        return None

    def release(self, order: Order) -> None:
        self.reserved -= order.reserved_cash
        for o, n in order.reserved_tokens.items():
            self.reserved_tokens[o] -= n
        order.reserved_cash = 0
        order.reserved_tokens = {}

    @staticmethod
    def _open_px(outcome: Outcome, side: Side, px: int) -> int:
        """Price paid per opened unit: buys open the same outcome at px;
        net-mode sells open the other outcome at 1 - px."""
        return px if side is Side.BUY else complement(px)

    @staticmethod
    def _fee_input(order: Order, px: int, size: int, plan: Plan, is_maker: bool) -> FeeInput:
        revenue = notional(px, size) if order.side is Side.SELL else -notional(px, size)
        if order.side is Side.BUY:
            revenue += plan.close * ONE_DOLLAR // CENTIS_PER_CONTRACT
        else:
            revenue -= plan.open * ONE_DOLLAR // CENTIS_PER_CONTRACT
        return FeeInput(order.order_id, px, size, is_maker, plan.open == 0, revenue)

    # ---- fills ---------------------------------------------------------
    def fill(self, order: Order, px: int, size: int, is_maker: bool) -> FeeCharge:
        """Apply a fill of ``size`` at outcome price ``px``. The order's
        reservation is released and re-made for what remains."""
        self.release(order)
        plan = self.plan(order.outcome, order.side, size)
        if plan is None:  # pragma: no cover - reserve() guarantees tokens
            raise RuntimeError("fill without tokens")
        fee_in = self._fee_input(order, px, size, plan, is_maker)
        charge = self.fees.charge(fee_in)
        self.cash += fee_in.revenue - charge.total
        self.holdings[plan.close_outcome] -= plan.close
        self.holdings[plan.open_outcome] += plan.open
        order.remaining -= size
        if order.remaining:
            self.reserve(order, check=False)
        return charge

    # ---- tokens mode ---------------------------------------------------
    def split(self, size: int) -> None:
        """Turn ``size`` centis of cash ($1 each) into YES + NO pairs."""
        self._tokens_only()
        cost = notional(ONE_DOLLAR, size)
        if size <= 0 or cost > self.available:
            raise ValueError("cannot split: bad size or not enough cash")
        self.cash -= cost
        self.holdings[Outcome.YES] += size
        self.holdings[Outcome.NO] += size

    def merge(self, size: int) -> None:
        """Turn ``size`` centis of YES + NO pairs back into $1 each."""
        self._tokens_only()
        if size <= 0 or min(self.free_tokens(o) for o in Outcome) < size:
            raise ValueError("cannot merge: bad size or not enough free pairs")
        self.holdings[Outcome.YES] -= size
        self.holdings[Outcome.NO] -= size
        self.cash += notional(ONE_DOLLAR, size)

    def _tokens_only(self) -> None:
        if self.mode is not PositionMode.TOKENS:
            raise ValueError("split and merge need tokens position mode")

    # ---- settlement and marking ---------------------------------------
    def settle(self, settle_fraction: int) -> tuple[int, int]:
        """Pay out every holding; returns ``(payout, fees)`` in micros."""
        payout = fees = 0
        for outcome, value in ((Outcome.YES, settle_fraction), (Outcome.NO, complement(settle_fraction))):
            n = self.holdings[outcome]
            if n:
                payout += value * n // CENTIS_PER_CONTRACT
                fees += self.fees.settle_fee(value, n)
            self.holdings[outcome] = 0
        self.cash += payout - fees
        return payout, fees

    def equity(self, mark: Fraction | None) -> int:
        """Cash plus holdings valued at YES price ``mark`` (floored)."""
        if mark is None:
            return self.cash
        yes, no = self.holdings[Outcome.YES], self.holdings[Outcome.NO]
        num, den = mark.numerator, mark.denominator
        value = yes * num + no * (ONE_DOLLAR * den - num)
        return self.cash + value // (CENTIS_PER_CONTRACT * den)
