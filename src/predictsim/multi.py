"""Multi-outcome markets: Polymarket negative-risk events and HIP-4 questions.

Both venues list each outcome as its own binary market with its own book,
linked by conversions. PredictSim runs them in portfolio mode
(:func:`predictsim.portfolio.run_portfolio` with ``groups``): every outcome is
a market with its own events and :class:`MarketSpec`, and the group adds the
venue's conversions to their :class:`Context`.

Polymarket (https://docs.polymarket.com/concepts/negative-risk and
https://docs.polymarket.com/concepts/markets-events): "Exactly one market in
the group resolves Yes, while every other market resolves No." "A No share in
any market can be converted into 1 Yes share in every other market"
(:meth:`Context.convert`).

HIP-4 (https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets,
the deployer actions page and the exchange endpoint page): "Questions are
collections of outcomes where exactly one outcome will settle to Yes, and all
others will settle to No." A question with N named outcomes has N + 1, the
fallback ("other") being created automatically; question outcomes "must
settle to exactly 0 or 1". ``negateOutcome`` converts "X No shares from an
outcome associated with a question into X Yes shares of every other outcome
associated with the question" (:meth:`Context.negate`); ``mergeQuestion``
merges "X Yes shares from each outcome associated to the same question into
X quote tokens" (:meth:`Context.merge_question`).

Not stated by either venue, so chosen by PredictSim:

* HIP-4: whether the fallback takes part in ``negateOutcome`` and
  ``mergeQuestion``. PredictSim counts it as an outcome of the question, the
  only reading under which both stay fully collateralized (without it, a
  fallback win would leave a merged set worth $0).
* No fee on any conversion (none is published).
* Conversions are refused once any outcome of the group has settled.
* ``mergeQuestion`` credits its cash to the market whose context called it;
  conversions move tokens between markets without cash, so per-market PnL
  inside a group is an attribution and only the group total is exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from predictsim.orders import Outcome
from predictsim.units import ONE_DOLLAR, notional
from predictsim.venues.hip4 import HIP4Profile
from predictsim.venues.polymarket import PolymarketProfile

if TYPE_CHECKING:
    from predictsim.engine import Engine


@dataclass(frozen=True, slots=True)
class NegRiskEvent:
    """A Polymarket negative-risk event: the market ids of its outcomes,
    including any "Other" market."""

    market_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HIP4Question:
    """A HIP-4 question: its named outcomes' market ids and its fallback's."""

    outcomes: tuple[str, ...]
    fallback: str

    @property
    def market_ids(self) -> tuple[str, ...]:
        return (*self.outcomes, self.fallback)


OutcomeGroup = NegRiskEvent | HIP4Question


class GroupState:
    """One group bound to the engines of its outcomes during a run."""

    def __init__(self, group: OutcomeGroup, engines: list[Engine]) -> None:
        ids = group.market_ids
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise ValueError(f"a group needs two or more distinct markets, got {ids}")
        venue = PolymarketProfile if isinstance(group, NegRiskEvent) else HIP4Profile
        for e in engines:
            if not isinstance(e.spec.venue, venue):
                raise ValueError(f"market {e.spec.market_id} is not a {venue.__name__} market")
        self.group = group
        self.engines = engines
        self.winners = 0

    # ---- conversions -----------------------------------------------------
    def convert(self, engine: Engine, size: int) -> None:
        """Polymarket: ``size`` NO of this market into ``size`` YES of every other."""
        self._need(NegRiskEvent, "convert")
        self._no_to_yes(engine, size)

    def negate(self, engine: Engine, size: int) -> None:
        """HIP-4 ``negateOutcome``: ``size`` NO into ``size`` YES of every
        other outcome of the question, the fallback included."""
        self._need(HIP4Question, "negate")
        self._no_to_yes(engine, size)

    def merge_question(self, engine: Engine, size: int) -> None:
        """HIP-4 ``mergeQuestion``: ``size`` YES of every outcome into cash."""
        self._need(HIP4Question, "merge_question")
        self._check_live(size)
        if any(e.account.free_tokens(Outcome.YES) < size for e in self.engines):
            raise ValueError("merge_question needs free YES tokens on every outcome")
        for e in self.engines:
            e.account.take_tokens(Outcome.YES, size)
        engine.account.credit(notional(ONE_DOLLAR, size))
        self._changed(engine)

    def _no_to_yes(self, engine: Engine, size: int) -> None:
        self._check_live(size)
        engine.account.take_tokens(Outcome.NO, size)
        for e in self.engines:
            if e is not engine:
                e.account.add_tokens(Outcome.YES, size)
        self._changed(engine)

    def _need(self, kind: type, what: str) -> None:
        if not isinstance(self.group, kind):
            raise ValueError(f"{what} is not available on a {type(self.group).__name__}")

    def _check_live(self, size: int) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if any(e.exchange.settlement is not None for e in self.engines):
            raise ValueError("an outcome of this group has settled")

    def _changed(self, engine: Engine) -> None:
        for e in self.engines:
            e.sync()
            e.holdings_changed()

    # ---- settlement --------------------------------------------------------
    def on_settle(self, engine: Engine, settle_fraction: int) -> None:
        """Check one outcome's settlement against the venue's rule."""
        mid = engine.spec.market_id
        if settle_fraction not in (0, ONE_DOLLAR):
            raise ValueError(f"{mid}: outcomes of a group settle to exactly 0 or 1")
        if settle_fraction:
            self.winners += 1
            if self.winners > 1:
                raise ValueError(f"{mid}: a second outcome of the group settled Yes")

    def check_final(self) -> None:
        """Once every outcome has settled, exactly one must have won."""
        if all(e.exchange.settlement is not None for e in self.engines) and self.winners != 1:
            raise ValueError(f"no outcome of {self.group.market_ids} settled Yes")
