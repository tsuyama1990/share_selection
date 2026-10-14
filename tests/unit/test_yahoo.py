import datetime
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from src.yahoo import YahooClient


def fake_ticker(fast_ok=True, info_ok=True):
    t = mock.MagicMock()
    if fast_ok:
        t.fast_info = SimpleNamespace(market_cap=5.0, last_price=7.0)
    else:
        type(t).fast_info = mock.PropertyMock(side_effect=RuntimeError("boom"))
    if info_ok:
        t.info = {"longName": "Foo"}
    else:
        type(t).info = mock.PropertyMock(side_effect=RuntimeError("boom"))
    t.financials = pd.DataFrame({"a": [1]})
    t.balance_sheet = pd.DataFrame({"b": [1]})
    t.cashflow = pd.DataFrame({"c": [1]})
    t.quarterly_income_stmt = pd.DataFrame({"2025-09-30": {"Diluted EPS": 12.5}})
    t.history.side_effect = lambda period, interval="1d": pd.DataFrame({"Close": [1.0]}, index=[period + interval])
    return t


def make_client():
    return YahooClient(0.0, "1y", "max")


def test_download_collects_all_parts():
    with mock.patch("src.yahoo.yf.Ticker", return_value=fake_ticker()) as ticker_cls:
        raw = make_client().download("1234.T")
    ticker_cls.assert_called_once_with("1234.T")
    assert raw["info"] == {"longName": "Foo"}
    assert raw["fast_info"] == {"market_cap": 5.0, "last_price": 7.0}
    assert list(raw["history"].index) == ["1y1d"]
    assert list(raw["history_monthly"].index) == ["max1mo"]
    assert raw["quarterly_income"].loc["Diluted EPS", "2025-09-30"] == 12.5
    assert not raw["financials"].empty and not raw["balance_sheet"].empty and not raw["cashflow"].empty


def test_download_survives_missing_info_and_fast_info():
    with mock.patch("src.yahoo.yf.Ticker", return_value=fake_ticker(fast_ok=False, info_ok=False)):
        raw = make_client().download("1234.T")
    assert raw["info"] == {}
    assert raw["fast_info"] == {}


def test_download_sleeps_before_requesting():
    with mock.patch("src.yahoo.yf.Ticker", return_value=fake_ticker()), mock.patch("src.yahoo.time.sleep") as sleep:
        YahooClient(0.5, "1y", "max").download("1234.T")
    sleep.assert_called_once_with(0.5)


def test_adjusted_close_uses_adjusted_naive_dates():
    index = pd.DatetimeIndex(["2025-01-06", "2025-01-07"], tz="Asia/Tokyo")
    ticker = mock.MagicMock()
    ticker.history.return_value = pd.DataFrame({"Close": [1.0, 2.0]}, index=index)
    with mock.patch("src.yahoo.yf.Ticker", return_value=ticker):
        series = YahooClient(0.0, "1y", "max").adjusted_close("1.T", datetime.date(2025, 1, 1))
    ticker.history.assert_called_once_with(start=datetime.date(2025, 1, 1), auto_adjust=True)
    assert series.index.tz is None and list(series.index.strftime("%Y-%m-%d")) == ["2025-01-06", "2025-01-07"]
