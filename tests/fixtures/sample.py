"""Loader for the fixture cache sample (exported by export_sample.py)."""

import datetime
import gzip
import json
from pathlib import Path

from src.cache import FRAME_KEYS, StockCache

SAMPLE = Path(__file__).parent / "sample_cache.json.gz"


def load_sample(cache: StockCache) -> list[str]:
    """Insert the fixture rows (stored JSON strings) into a cache; return the tickers."""
    with gzip.open(SAMPLE, "rt", encoding="utf-8") as f:
        rows = json.load(f)
    cols = ["info", "fast_info", *FRAME_KEYS]
    names, marks = ", ".join(cols), ", ".join("?" for _ in cols)
    for ticker, row in rows.items():
        cache.con.execute(
            f"INSERT INTO stock_cache (ticker, updated_at, {names}) VALUES (?, ?, {marks})",
            [ticker, datetime.datetime.now(), *(row.get(c) for c in cols)],
        )
    return sorted(rows)
