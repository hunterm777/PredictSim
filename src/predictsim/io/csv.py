"""CSV event loader and result exporters.

The event file is one row per event or per book level; see docs/schema.md.
``mapping`` maps PredictSim's logical column names to the file's own column
names, for example ``{"ts": "timestamp_ns", "px": "price"}``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from predictsim.events import Band, BookSide, Delta, Event, GridChange, Level, Settle, Side, Snapshot, Trade
from predictsim.orders import Fill, Order
from predictsim.units import complement, to_centis, to_micros

COLUMNS = ("ts", "type", "side", "px", "sz", "start", "end", "step", "settle_fraction")


class SchemaError(ValueError):
    """A row that does not fit the event schema, naming its row number."""


def _book_level(side: str, px: int) -> tuple[BookSide, int]:
    if side == "bid":
        return BookSide.BID, px
    if side == "ask":
        return BookSide.ASK, px
    if side == "no_bid":
        return BookSide.ASK, complement(px)
    if side == "no_ask":
        return BookSide.BID, complement(px)
    raise ValueError(f"unknown book side {side!r}")


def events_from_rows(
    rows: Iterable[Mapping[str, object]], mapping: Mapping[str, str] | None = None
) -> Iterator[Event]:
    """Turn rows of logical columns into events. Consecutive ``snapshot`` (or
    ``grid``) rows with the same ``ts`` form one Snapshot (or GridChange)."""
    names = {c: (mapping or {}).get(c, c) for c in COLUMNS}
    group: list[tuple[int, dict[str, str]]] = []

    def flush() -> Iterator[Event]:
        if group:
            yield _group_event(group)
            group.clear()

    for n, raw in enumerate(rows, start=1):
        row = {c: _cell(raw.get(names[c])) for c in COLUMNS}
        kind = row["type"]
        if group and (kind != group[0][1]["type"] or row["ts"] != group[0][1]["ts"]):
            yield from flush()
        try:
            if kind in ("snapshot", "grid"):
                group.append((n, row))
            elif kind == "delta":
                side, px = _book_level(row["side"], to_micros(row["px"]))
                yield Delta(int(row["ts"]), side, px, to_centis(row["sz"]))
            elif kind == "trade":
                side_, px = _trade_side(row["side"], to_micros(row["px"]))
                yield Trade(int(row["ts"]), px, to_centis(row["sz"]), side_)
            elif kind == "settle":
                yield Settle(int(row["ts"]), to_micros(row["settle_fraction"]))
            else:
                raise ValueError(f"unknown event type {kind!r}")
        except (ValueError, ArithmeticError) as exc:
            raise SchemaError(f"row {n}: {exc}") from exc
    yield from flush()


def _trade_side(side: str, px: int) -> tuple[Side, int]:
    """Aggressor side in YES space; ``no_buy``/``no_sell`` are NO-token prints."""
    table = {"buy": (Side.BUY, px), "sell": (Side.SELL, px)}
    table["no_buy"] = (Side.SELL, complement(px))
    table["no_sell"] = (Side.BUY, complement(px))
    if side not in table:
        raise ValueError(f"unknown trade side {side!r}")
    return table[side]


def _group_event(group: list[tuple[int, dict[str, str]]]) -> Event:
    n0, first = group[0]
    try:
        ts = int(first["ts"])
        if first["type"] == "grid":
            bands = tuple(
                Band(to_micros(r["start"]), to_micros(r["end"]), to_micros(r["step"])) for _, r in group
            )
            return GridChange(ts, bands)
        bids: list[Level] = []
        asks: list[Level] = []
        for _, r in group:
            if not r["side"]:
                continue  # an empty-book marker row
            side, px = _book_level(r["side"], to_micros(r["px"]))
            (bids if side is BookSide.BID else asks).append((px, to_centis(r["sz"])))
        return Snapshot(ts, tuple(sorted(bids)), tuple(sorted(asks)))
    except (ValueError, ArithmeticError) as exc:
        raise SchemaError(f"rows {n0}-{group[-1][0]}: {exc}") from exc


def _cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def load_csv(path: str | Path, mapping: Mapping[str, str] | None = None) -> list[Event]:
    """Read every event from a CSV file."""
    with open(path, newline="", encoding="utf-8") as fh:
        return list(events_from_rows(csv.DictReader(fh), mapping))


def write_fills(path: str | Path, fills: Iterable[Fill]) -> None:
    """Fill log: time, order, outcome, side, price, size, maker/taker, fee."""
    _write(
        path,
        ("ts", "order_id", "outcome", "side", "px_micros", "size_centis", "liquidity", "fee_micros"),
        (
            (f.ts, f.order_id, f.outcome, f.side, f.px, f.size, "maker" if f.is_maker else "taker", f.fee)
            for f in fills
        ),
    )


def write_orders(path: str | Path, orders: Iterable[Order]) -> None:
    head = (
        "order_id",
        "ts",
        "outcome",
        "side",
        "type",
        "px_micros",
        "size_centis",
        "filled_centis",
        "status",
        "live_ts",
        "done_ts",
        "reason",
    )
    _write(
        path,
        head,
        (
            (
                o.order_id,
                o.ts,
                o.outcome,
                o.side,
                o.order_type,
                o.px,
                o.size,
                o.filled,
                o.status,
                "" if o.live_ts is None else o.live_ts,
                "" if o.done_ts is None else o.done_ts,
                o.reason,
            )
            for o in orders
        ),
    )


def write_equity(path: str | Path, equity: Iterable[tuple[int, int]]) -> None:
    _write(path, ("ts", "equity_micros"), equity)


def _write(path: str | Path, header: tuple[str, ...], rows: Iterable[Iterable[object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
