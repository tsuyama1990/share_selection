import pandas as pd

from src.cache import StockCache, refresh

TZ = "Asia/Tokyo"


class FakeClient:
    def download(self, ticker):
        return {
            "info": {"longName": "Foo"},
            "fast_info": {"market_cap": 5.0},
            "financials": pd.DataFrame({"2023": {"Total Revenue": 10.0}}),
            "history": pd.DataFrame(
                {"Close": [1.0, 2.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize(TZ)
            ),
        }


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


def test_put_get_roundtrip(tmp_path):
    with StockCache(str(tmp_path / "c.duckdb"), TZ) as cache:
        assert cache.get("1234.T") is None
        assert not cache.is_fresh("1234.T", 3)
        assert refresh(cache, FakeClient(), "1234.T", 3) is None
        assert cache.is_fresh("1234.T", 3)
        data = cache.get("1234.T")
    assert data.info["longName"] == "Foo"
    assert data.fast_info["market_cap"] == 5.0
    assert data.financials.loc["Total Revenue"].iloc[0] == 10.0
    assert list(data.history["Close"]) == [1.0, 2.0]
    assert data.history.index.tz is None
    assert data.balance_sheet.empty


def test_history_dates_roundtrip_in_market_timezone(tmp_path):
    monthly = pd.DataFrame(
        {"Low": [1.0, 2.0, 3.0]}, index=pd.DatetimeIndex(["2008-09-01", "2008-10-01", "2008-11-01"], tz=TZ)
    )
    daily = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.DatetimeIndex(["2024-01-04", "2024-01-05"], tz=TZ))
    with StockCache(str(tmp_path / "c.duckdb"), TZ) as cache:
        cache.put("1234.T", {"history": daily, "history_monthly": monthly})
        data = cache.get("1234.T")
    assert data.history_monthly.index.tz is None
    assert list(data.history_monthly.index) == list(monthly.index.tz_localize(None))
    assert list(data.history.index) == list(daily.index.tz_localize(None))
    assert data.history_monthly.loc["2008-10-01", "Low"] == 2.0
