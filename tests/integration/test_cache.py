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


def test_fetched_range(tmp_path):
    with StockCache(str(tmp_path / "c.duckdb"), "Asia/Tokyo") as cache:
        assert cache.fetched_range() == (None, None)
        cache.put("1.T", {})
        lo, hi = cache.fetched_range()
        assert lo == hi and lo is not None


def test_corrupt_entry_reads_as_missing(tmp_path):
    with StockCache(str(tmp_path / "c.duckdb"), TZ) as cache:
        cache.put("1.T", {})
        cache.con.execute("UPDATE stock_cache SET financials = '\"not a frame\"' WHERE ticker = '1.T'")
        assert cache.get("1.T") is None
