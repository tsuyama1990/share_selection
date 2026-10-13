"""Export a few tickers from the full cache into ``sample_cache.json.gz`` (regression fixture).

Usage: ``uv run python tests/fixtures/export_sample.py [stocks_cache.duckdb]``
"""

import gzip
import json
import sys
from pathlib import Path

import duckdb

TICKERS = ["6430.T", "7713.T", "5542.T", "6599.T", "7203.T", "6920.T", "8935.T", "2491.T"]
COLUMNS = ["info", "fast_info", "financials", "balance_sheet", "history", "history_monthly", "cashflow"]
OUT = Path(__file__).with_name("sample_cache.json.gz")


def main(db_path: str) -> None:
    """
    Write the sample tickers' raw cache rows (JSON strings, as stored) to ``OUT``.

    Parameters
    ----------
    db_path : str
        Path of the full DuckDB cache.
    """
    con = duckdb.connect(db_path, read_only=True)
    rows = {}
    for t in TICKERS:
        row = con.execute(f"SELECT {', '.join(COLUMNS)} FROM stock_cache WHERE ticker = ?", [t]).fetchone()
        if row is None:
            raise SystemExit(f"{t} not in cache")
        rows[t] = dict(zip(COLUMNS, row, strict=True))
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(rows)} tickers to {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "stocks_cache.duckdb")
