"""Parquet event loader (needs the ``parquet`` extra: pyarrow). Same logical
schema and column mapping as the CSV loader."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from predictsim.events import Event
from predictsim.io.csv import events_from_rows


def load_parquet(path: str | Path, mapping: Mapping[str, str] | None = None) -> list[Event]:
    """Read every event from a Parquet file."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("Parquet support needs: pip install predictsim[parquet]") from exc
    table = pq.read_table(path)
    return list(events_from_rows(table.to_pylist(), mapping))
