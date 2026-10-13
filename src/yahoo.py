"""Yahoo Finance downloader."""

import time
from typing import Any

import yfinance as yf


class YahooClient:
    """Downloads raw stock data from Yahoo Finance."""

    def __init__(self, sleep_time: float, daily_history_period: str, monthly_history_period: str):
        self.sleep_time = sleep_time
        self.daily_history_period = daily_history_period
        self.monthly_history_period = monthly_history_period

    def download(self, ticker: str) -> dict[str, Any]:
        """Raw data dict (as accepted by ``StockData.from_dict``); raises if the frames cannot be downloaded."""
        time.sleep(self.sleep_time)
        t = yf.Ticker(ticker)

        try:
            fast_info = {"market_cap": t.fast_info.market_cap, "last_price": t.fast_info.last_price}
        except Exception:
            fast_info = {}
        try:
            info = t.info
        except Exception:
            info = {}

        return {
            "info": info,
            "fast_info": fast_info,
            "financials": t.financials,
            "balance_sheet": t.balance_sheet,
            "history": t.history(period=self.daily_history_period),
            "history_monthly": t.history(period=self.monthly_history_period, interval="1mo"),
            "cashflow": t.cashflow,
            "quarterly_income": t.quarterly_income_stmt,
        }
