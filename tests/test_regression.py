"""Golden-file regression test: screener output on a fixed cached sample.

The sample (``tests/fixtures/sample_cache.json.gz``) is exported from the full
cache by ``tests/fixtures/export_sample.py``. After an intended change of the
screening behavior or ``config.yaml``, regenerate the golden CSV with::

    UPDATE_GOLDEN=1 uv run pytest tests/test_regression.py

and review the diff of ``tests/fixtures/golden_screening.csv`` before committing.
"""

import datetime
import gzip
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from src.cache import FRAME_KEYS, StockCache
from src.config import CFG
from src.screener import Screener

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_cache.json.gz"
GOLDEN = FIXTURES / "golden_screening.csv"


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


def screen_sample(tmp_path: Path) -> pd.DataFrame:
    """Run the configured screener on the sample and return the report frame."""
    with StockCache(str(tmp_path / "sample.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = load_sample(cache)
        screener = Screener.from_config(CFG)
        screened = [screener.screen(d) for t in tickers if (d := cache.get(t)) is not None]
        results = [r.row for r in screened if r.passed]
    df = pd.DataFrame(results).sort_values("Ticker").reset_index(drop=True)
    return df[[c for c in CFG["output"]["columns"] if c in df.columns]]


def test_screener_matches_golden(tmp_path):
    actual = screen_sample(tmp_path)
    if os.environ.get("UPDATE_GOLDEN"):
        actual.to_csv(GOLDEN, index=False)
        pytest.skip(f"golden regenerated: {GOLDEN}")
    expected = pd.read_csv(GOLDEN)
    assert len(actual) > 0
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected, check_dtype=False, rtol=1e-6)
