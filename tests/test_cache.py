import datetime

import duckdb
import pandas as pd

from src.cache import StockCache

TZ = "Asia/Tokyo"


def quarterly_frame() -> pd.DataFrame:
    cols = pd.to_datetime(["2025-09-30", "2024-09-30"])
    return pd.DataFrame({cols[0]: [12.5, 1000.0], cols[1]: [7.0, 990.0]}, index=["Diluted EPS", "Basic Average Shares"])


def test_quarterly_income_round_trip(tmp_path):
    frame = quarterly_frame()
    with StockCache(str(tmp_path / "c.duckdb"), TZ) as cache:
        cache.put("1234.T", {"quarterly_income": frame})
        data = cache.get("1234.T")
    assert data is not None
    got = data.quarterly_income
    assert list(got.index) == list(frame.index)
    assert list(got.columns) == list(frame.columns)
    assert got.to_numpy().tolist() == frame.to_numpy().tolist()


def test_missing_quarterly_income_is_empty(tmp_path):
    with StockCache(str(tmp_path / "c.duckdb"), TZ) as cache:
        cache.put("1234.T", {})
        data = cache.get("1234.T")
    assert data is not None and data.quarterly_income.empty


def test_entry_without_quarterly_income_is_not_fresh(tmp_path):
    with StockCache(str(tmp_path / "c.duckdb"), TZ) as cache:
        cache.put("NEW.T", {"quarterly_income": quarterly_frame()})
        cache.con.execute(
            "INSERT INTO stock_cache (ticker, updated_at, info, fast_info) VALUES ('OLD.T', ?, '{}', '{}')",
            [datetime.datetime.now()],
        )
        assert cache.is_fresh("NEW.T", 1)
        assert not cache.is_fresh("OLD.T", 1)


def test_old_schema_is_migrated(tmp_path):
    path = str(tmp_path / "old.duckdb")
    con = duckdb.connect(path)
    con.execute(
        "CREATE TABLE stock_cache (ticker TEXT PRIMARY KEY, updated_at TIMESTAMP, info JSON, fast_info JSON,"
        " financials JSON, balance_sheet JSON, history JSON, history_monthly JSON, cashflow JSON)"
    )
    con.execute("INSERT INTO stock_cache (ticker, updated_at) VALUES ('OLD.T', now())")
    con.close()
    with StockCache(path, TZ) as cache:
        cols = [r[0] for r in cache.con.execute("DESCRIBE stock_cache").fetchall()]
        assert "quarterly_income" in cols
        assert not cache.is_fresh("OLD.T", 1)
