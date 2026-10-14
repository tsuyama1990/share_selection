import unittest

import pandas as pd

from src.cache import StockCache, refresh


class FakeClient:
    def download(self, ticker):
        return {
            "info": {"longName": "Foo"},
            "fast_info": {"market_cap": 5.0},
            "financials": pd.DataFrame({"2023": {"Total Revenue": 10.0}}),
            "history": pd.DataFrame(
                {"Close": [1.0, 2.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize("Asia/Tokyo")
            ),
        }


class TestStockCache(unittest.TestCase):
    def test_put_get_roundtrip(self):
        import pathlib
        import tempfile

        with (
            tempfile.TemporaryDirectory() as tmp,
            StockCache(str(pathlib.Path(tmp) / "c.duckdb"), "Asia/Tokyo") as cache,
        ):
            self.assertIsNone(cache.get("1234.T"))
            self.assertFalse(cache.is_fresh("1234.T", 3))
            self.assertIsNone(refresh(cache, FakeClient(), "1234.T", 3))
            self.assertTrue(cache.is_fresh("1234.T", 3))
            data = cache.get("1234.T")
            self.assertEqual(data.info["longName"], "Foo")
            self.assertEqual(data.fast_info["market_cap"], 5.0)
            self.assertEqual(data.financials.loc["Total Revenue"].iloc[0], 10.0)
            self.assertEqual(list(data.history["Close"]), [1.0, 2.0])
            self.assertIsNone(data.history.index.tz)
            self.assertTrue(data.balance_sheet.empty)

    def test_history_dates_roundtrip_in_market_timezone(self):
        import pathlib
        import tempfile

        monthly = pd.DataFrame(
            {"Low": [1.0, 2.0, 3.0]},
            index=pd.DatetimeIndex(["2008-09-01", "2008-10-01", "2008-11-01"], tz="Asia/Tokyo"),
        )
        daily = pd.DataFrame(
            {"Close": [1.0, 2.0]}, index=pd.DatetimeIndex(["2024-01-04", "2024-01-05"], tz="Asia/Tokyo")
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            StockCache(str(pathlib.Path(tmp) / "c.duckdb"), "Asia/Tokyo") as cache,
        ):
            cache.put("1234.T", {"history": daily, "history_monthly": monthly})
            data = cache.get("1234.T")
        self.assertIsNone(data.history_monthly.index.tz)
        self.assertEqual(list(data.history_monthly.index), list(monthly.index.tz_localize(None)))
        self.assertEqual(list(data.history.index), list(daily.index.tz_localize(None)))
        self.assertEqual(data.history_monthly.loc["2008-10-01", "Low"], 2.0)
