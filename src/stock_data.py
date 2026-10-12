"""Typed container for one ticker's raw data (the only place that knows its shape)."""

import contextlib
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

_FRAMES = ("financials", "balance_sheet", "cashflow", "history", "history_monthly")


def _to_naive_datetime_index(df: pd.DataFrame, market_tz: str | None = None) -> pd.DataFrame:
    """
    Ensure the DataFrame index is datetime and tz-naive.

    A tz-aware index is converted to the market timezone first (so a bar
    stamped 2008-09-30 15:00 UTC becomes 2008-10-01 in Tokyo) and then
    reduced to dates (bars are daily or monthly).

    Parameters
    ----------
    df : pd.DataFrame
        Stock history DataFrame.
    market_tz : Optional[str]
        Market timezone name (e.g., 'Asia/Tokyo'). If None, a tz-aware index
        just loses its tz.

    Returns
    -------
    pd.DataFrame
        DataFrame with tz-naive datetime index (empty frames are returned as is).
    """
    if df.empty:
        return df
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        with contextlib.suppress(Exception):
            df.index = pd.to_datetime(df.index)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        if market_tz is not None:
            df.index = df.index.tz_convert(market_tz).normalize()
        df.index = df.index.tz_localize(None)
    return df


@dataclass(frozen=True)
class StockData:
    """
    Raw data of one ticker.

    Financial statements have line items as index and periods as columns
    (latest first); histories have dates as index.
    """

    ticker: str
    info: dict[str, Any] = field(default_factory=dict)
    fast_info: dict[str, Any] = field(default_factory=dict)
    financials: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_sheet: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow: pd.DataFrame = field(default_factory=pd.DataFrame)
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    history_monthly: pd.DataFrame = field(default_factory=pd.DataFrame)

    @classmethod
    def from_dict(cls, ticker: str, d: dict[str, Any], market_tz: str | None = None) -> "StockData":
        """
        Build from a raw dict, filling missing parts and normalizing histories.

        Parameters
        ----------
        ticker : str
            Ticker symbol (e.g., '7203.T').
        d : Dict[str, Any]
            Raw data with any of 'info', 'fast_info' and the frame keys.
        market_tz : Optional[str]
            Market timezone; tz-aware history indexes are converted to it and
            exposed as naive dates.

        Returns
        -------
        StockData
            Data with empty defaults and tz-naive history indexes.
        """
        frames: dict[str, pd.DataFrame] = {k: d[k] if d.get(k) is not None else pd.DataFrame() for k in _FRAMES}
        for key in ("history", "history_monthly"):
            frames[key] = _to_naive_datetime_index(frames[key], market_tz)
        return cls(ticker, d.get("info") or {}, d.get("fast_info") or {}, **frames)
