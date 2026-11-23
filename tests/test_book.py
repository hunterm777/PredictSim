"""M1: a fixture of snapshots and deltas replays to the expected book at every step."""

from fractions import Fraction

import pytest

from predictsim.book import BookError, OrderBook
from predictsim.events import BookSide, Delta, Snapshot
from predictsim.io.csv import load_csv
from predictsim.spec import uniform_grid
from tests.conftest import FIXTURES

# (bids best first, asks best first) after each event, in micros and centis
EXPECTED = [
    ([(300_000, 1000)], [(330_000, 500)]),
    ([(310_000, 400), (300_000, 1000)], [(330_000, 500)]),
    ([(310_000, 400), (300_000, 1000)], [(320_000, 750), (330_000, 500)]),
    ([(310_000, 400)], [(320_000, 750), (330_000, 500)]),
    ([(310_000, 400)], [(320_000, 750), (330_000, 500), (340_000, 300)]),
    ([(310_000, 400)], [(320_000, 750), (340_000, 300)]),
    ([], []),
    ([(500_000, 100)], [(550_000, 200)]),
]


def test_fixture_replays_to_expected_book_at_every_step() -> None:
    grid = uniform_grid(10_000)
    book = OrderBook(grid.contains)
    events = load_csv(FIXTURES / "book_replay.csv")
    assert len(events) == len(EXPECTED)
    for i, (ev, (bids, asks)) in enumerate(zip(events, EXPECTED, strict=True)):
        if isinstance(ev, Snapshot):
            book.apply_snapshot(ev, i)
        else:
            assert isinstance(ev, Delta)
            book.apply_delta(ev, i)
        assert book.depth(10) == (bids, asks), f"step {i}"


def test_queries() -> None:
    book = OrderBook()
    assert book.best_bid() is None and book.mid() is None and book.spread() is None
    book.apply_snapshot(Snapshot(1, ((400_000, 100), (390_000, 50)), ((430_000, 70),)), 0)
    assert book.best_bid() == 400_000 and book.best_ask() == 430_000
    assert book.mid() == Fraction(415_000) and book.spread() == 30_000
    assert book.size_at(BookSide.BID, 390_000) == 50
    assert book.size_at(BookSide.ASK, 999) == 0
    assert book.depth(1) == ([(400_000, 100)], [(430_000, 70)])
    assert book.depth(0) == ([], [])
    copy = book.copy()
    copy.apply_delta(Delta(2, BookSide.BID, 400_000, 0), 1)
    assert book.best_bid() == 400_000 and copy.best_bid() == 390_000


@pytest.mark.parametrize(
    "event",
    [
        Delta(1, BookSide.BID, 430_000, 10),
        Delta(1, BookSide.ASK, 400_000, 10),
        Delta(1, BookSide.BID, 405_000, 10),
        Delta(1, BookSide.BID, 400_000, -1),
        Snapshot(1, ((450_000, 1),), ((440_000, 1),)),
        Snapshot(1, ((455_000, 1),), ()),
    ],
)
def test_bad_input_raises_with_index_or_is_skipped(event: Delta | Snapshot) -> None:
    grid = uniform_grid(10_000)
    strict = OrderBook(grid.contains)
    strict.apply_snapshot(Snapshot(0, ((400_000, 100),), ((430_000, 70),)), 0)
    lenient = strict.copy()
    lenient.strict = False
    apply = (
        (lambda b: b.apply_delta(event, 7))
        if isinstance(event, Delta)
        else (lambda b: b.apply_snapshot(event, 7))
    )
    with pytest.raises(BookError, match="event 7"):
        apply(strict)
    before = lenient.depth(5)
    assert apply(lenient) is False
    assert lenient.depth(5) == before


def test_removing_missing_level_is_harmless() -> None:
    book = OrderBook()
    assert book.apply_delta(Delta(1, BookSide.ASK, 500_000, 0), 0)
    assert book.best_ask() is None
