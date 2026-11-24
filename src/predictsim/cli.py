"""Command line: ``predictsim validate FILE --venue kalshi``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from predictsim.io.csv import SchemaError, load_csv
from predictsim.io.validate import validate
from predictsim.spec import MarketSpec, uniform_grid
from predictsim.units import to_micros
from predictsim.venues import HIP4Profile, KalshiProfile, PolymarketProfile, VenueProfile

VENUES: dict[str, Callable[[], VenueProfile]] = {
    "kalshi": KalshiProfile,
    "polymarket": lambda: PolymarketProfile(fee_rate=0),  # fees play no part in validation
    "hip4": HIP4Profile,
}


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="predictsim")
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check an event file before a backtest")
    v.add_argument("path", type=Path)
    v.add_argument("--venue", choices=sorted(VENUES), required=True)
    v.add_argument("--tick", help="uniform tick size in dollars, e.g. 0.001 (default: venue's)")
    v.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="NAME=COLUMN",
        help="map a schema column to a file column; repeatable",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    venue: VenueProfile = VENUES[args.venue]()
    grid = uniform_grid(to_micros(args.tick)) if args.tick else venue.default_grid()
    mapping = dict(m.split("=", 1) for m in args.map)
    try:
        if args.path.suffix == ".parquet":
            from predictsim.io.parquet import load_parquet

            events = load_parquet(args.path, mapping)
        else:
            events = load_csv(args.path, mapping)
    except (OSError, SchemaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    spec = MarketSpec("validate", venue, 0, 2**63 - 1, grid, 1, 1)
    issues = validate(events, spec)
    for issue in issues:
        print(issue)
    if issues:
        print(f"{len(issues)} problem(s) in {len(events)} events", file=sys.stderr)
        return 1
    print(f"OK: {len(events)} events")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
