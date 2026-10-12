"""Yahoo Finance downloader."""

import time
from typing import Any

import yfinance as yf


class YahooClient:
    """Downloads raw stock data from Yahoo Finance."""

    def __init__(self, sleep_time: float, daily_history_period: str, monthly_history_period: str):
        """
        Parameters
        ----------
        sleep_time : float
            Delay in seconds before each download (rate limiting).
        daily_history_period : str
            yfinance period of the daily history (e.g., '1y').
        monthly_history_period : str
            yfinance period of the monthly history (e.g., 'max').
        """
        self.sleep_time = sleep_time
        self.daily_history_period = daily_history_period
        self.monthly_history_period = monthly_history_period

    def download(self, ticker: str) -> dict[str, Any]:
        """
        Download info, fast_info and the financial/history frames.

        Parameters
        ----------
        ticker : str
            Ticker symbol (e.g., '7203.T').

        Returns
        -------
        Dict[str, Any]
            Raw data dict, as accepted by ``StockData.from_dict``.

        Raises
        ------
        Exception
            If the frames cannot be downloaded.
        """
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
        }
