"""M3 account fixtures: collateral, position modes, settlement payout."""

from fractions import Fraction

import pytest

from predictsim.account import Account
from predictsim.events import Settle, Side
from predictsim.fees import HIP4Fees, KalshiFees, PolymarketFees
from predictsim.orders import Order, OrderType, Outcome, to_yes
from predictsim.venues import HIP4Profile, PositionMode
from tests.helpers import Snapshot, make

BOOK = Snapshot(1, ((400_000, 1000),), ((420_000, 1000),))


def order(oid: int, outcome: Outcome, side: Side, px: int, size: int) -> Order:
    ys, yp = to_yes(outcome, side, px)
    return Order(oid, 0, outcome, side, px, size, OrderType.GTC, ys, yp)


def test_net_mode_sell_opens_no_and_buy_closes_it() -> None:
    acct = Account(10_000_000, PositionMode.NET, KalshiFees())
    sell = order(1, Outcome.YES, Side.SELL, 400_000, 1000)
    assert acct.reserve(sell) is None
    assert acct.reserved == 6_000_000 + 170_000  # 10 NO at 0.60 + fee 0.168 rounded to 0.17
    acct.fill(sell, 400_000, 1000, False)
    assert acct.position == -1000 and acct.net_yes == -1000  # one signed position
    assert acct.holdings == {Outcome.YES: 0, Outcome.NO: 1000}
    assert acct.cash == 10_000_000 - 6_000_000 - 170_000
    buy = order(2, Outcome.YES, Side.BUY, 420_000, 1000)
    acct.reserve(buy)
    acct.fill(buy, 420_000, 1000, False)
    assert acct.position == 0 and acct.is_flat
    # closing 10 NO by buying YES at 0.42 returns 10 x 0.58; fee 0.170520 -> 0.18 with rounding
    assert acct.cash == 3_830_000 + 5_800_000 - 180_000
    assert acct.reserved == 0


def test_tokens_mode_requires_tokens_to_sell() -> None:
    acct = Account(10_000_000, PositionMode.TOKENS, PolymarketFees("0.05"))
    assert acct.reserve(order(1, Outcome.YES, Side.SELL, 400_000, 100)) == "not enough tokens to sell"
    acct.split(300)
    assert acct.cash == 7_000_000 and acct.holdings[Outcome.NO] == 300
    sell = order(2, Outcome.NO, Side.SELL, 600_000, 200)
    assert acct.reserve(sell) is None and acct.free_tokens(Outcome.NO) == 100
    with pytest.raises(ValueError):
        acct.merge(200)
    acct.merge(100)
    assert acct.cash == 8_000_000
    acct.release(sell)
    assert acct.free_tokens(Outcome.NO) == 200


def test_split_merge_guards() -> None:
    net = Account(1_000_000, PositionMode.NET, KalshiFees())
    with pytest.raises(ValueError):
        net.split(100)
    tok = Account(1_000_000, PositionMode.TOKENS, KalshiFees())
    with pytest.raises(ValueError):
        tok.split(200)
    with pytest.raises(ValueError):
        Account(-1, PositionMode.NET, KalshiFees())


def test_settlement_payout_and_hip4_fees() -> None:
    ex, fills = make(HIP4Profile(taker_rate="0.0006"))
    ex.on_event(BOOK, 0)
    o = ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 300, OrderType.IOC)
    ex.arrive(o, 1)
    assert fills[0].fee == 0  # opening buy pays nothing
    assert ex.account.cash == 100_000_000 - 1_260_000
    ex.on_event(Settle(9, 1_000_000), 1)
    # YES pays $1 x 3; settlement fee 2 x 0.0006 x 3 = 0.0036
    assert ex.settlement == (9, 3_000_000, 3_600)
    assert ex.account.cash == 100_000_000 - 1_260_000 + 3_000_000 - 3_600
    assert ex.closed


def test_fractional_settlement_pays_both_sides() -> None:
    acct = Account(0, PositionMode.TOKENS, HIP4Fees(0, 0, 0))
    acct._tokens.update({Outcome.YES: 300, Outcome.NO: 100})
    # 3 YES x $0.25 + 1 NO x $0.75
    assert acct.settle(250_000) == (750_000 + 750_000, 0)
    assert acct.cash == 1_500_000 and acct.is_flat


def test_hip4_closing_sell_pays_fee() -> None:
    ex, fills = make(HIP4Profile(taker_rate="0.0006"))
    ex.on_event(BOOK, 0)
    ex.arrive(ex.new_order(1, Outcome.YES, Side.BUY, 420_000, 1000, OrderType.IOC), 1)
    ex.on_event(Snapshot(2, ((400_000, 1000),), ((420_000, 1000),)), 1)
    ex.arrive(ex.new_order(2, Outcome.YES, Side.SELL, 400_000, 1000, OrderType.IOC), 2)
    assert fills[-1].fee == 4_800  # 2 x 0.0006 x 0.40 x 10


def test_equity_marks() -> None:
    acct = Account(1_000_000, PositionMode.TOKENS, HIP4Fees(0, 0, 0))
    acct._tokens.update({Outcome.YES: 100, Outcome.NO: 50})
    assert acct.equity(None) == 1_000_000
    assert acct.equity(Fraction(415_000)) == 1_000_000 + 415_000 + 292_500
    assert acct.net_yes == 50 and not acct.is_flat


def test_net_mode_settles_signed_position() -> None:
    long_yes = Account(0, PositionMode.NET, KalshiFees())
    long_yes.position = 300
    assert long_yes.held(Outcome.YES) == 300 and long_yes.held(Outcome.NO) == 0
    assert long_yes.settle(1_000_000) == (3_000_000, 0) and long_yes.is_flat
    short = Account(0, PositionMode.NET, KalshiFees())
    short.position = -200  # 2 NO
    assert short.holdings == {Outcome.YES: 0, Outcome.NO: 200}
    assert short.equity(Fraction(400_000)) == 1_200_000
    assert short.settle(0) == (2_000_000, 0) and short.cash == 2_000_000
