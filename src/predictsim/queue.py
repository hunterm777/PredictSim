"""Maker queue-position models.

A resting order joins the back of its level: ``queue_ahead`` starts at the
displayed size there. Trades at its price drain the queue first, then fill
the order. Size that leaves the level without trading (cancels) moves the
queue according to the chosen model. Queue ahead can never exceed the
displayed size of the level.
"""

from __future__ import annotations

from enum import StrEnum


class QueueModel(StrEnum):
    PESSIMISTIC = "pessimistic"  # cancels never come from ahead of us
    PROPORTIONAL = "proportional"  # cancels come from ahead in proportion
    OPTIMISTIC = "optimistic"  # cancels come from ahead first


def after_cancels(model: QueueModel, queue_ahead: int, level_before: int, cancelled: int) -> int:
    """Queue ahead after ``cancelled`` centis leave a level that held
    ``level_before`` centis, before clamping to the new level size."""
    if cancelled <= 0 or queue_ahead <= 0:
        return queue_ahead
    if model is QueueModel.PESSIMISTIC:
        return queue_ahead
    if model is QueueModel.OPTIMISTIC:
        return queue_ahead - min(queue_ahead, cancelled)
    share = (cancelled * queue_ahead) // level_before if level_before > 0 else queue_ahead
    return queue_ahead - min(queue_ahead, share)


def on_level_change(model: QueueModel, queue_ahead: int, old_size: int, new_size: int, traded: int) -> int:
    """New queue ahead when a level moves from ``old_size`` to ``new_size``.
    Up to ``traded`` centis of a decrease are explained by trades already
    applied to the queue; the rest are cancels."""
    if new_size >= old_size:
        return queue_ahead
    decrease = old_size - new_size
    cancelled = decrease - min(decrease, traded)
    q = after_cancels(model, queue_ahead, old_size - (decrease - cancelled), cancelled)
    return min(q, new_size)


def on_trade(queue_ahead: int, trade_size: int) -> tuple[int, int]:
    """Apply a trade at the order's price: returns ``(new_queue_ahead,
    size left over to fill the order)``."""
    drained = min(queue_ahead, trade_size)
    return queue_ahead - drained, trade_size - drained
