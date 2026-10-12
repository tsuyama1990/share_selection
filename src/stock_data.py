"""Typed container for one ticker's raw data (the only place that knows its shape)."""
from dataclasses import dataclass, field
from typing import Any, Dict

import pandas as pd

_FRAMES = ('financials', 'balance_sheet', 'cashflow', 'history', 'history_monthly')


def _to_naive_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the DataFrame index is datetime and tz-naive.

    Parameters
    ----------
    df : pd.DataFrame
        Stock history DataFrame.

    Returns
    -------
    pd.DataFrame
        DataFrame with tz-naive datetime index (empty frames are returned as is).
    """
    if df.empty:
        return df
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            pass
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
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
    info: Dict[str, Any] = field(default_factory=dict)
    fast_info: Dict[str, Any] = field(default_factory=dict)
    financials: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_sheet: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow: pd.DataFrame = field(default_factory=pd.DataFrame)
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    history_monthly: pd.DataFrame = field(default_factory=pd.DataFrame)

    @classmethod
    def from_dict(cls, ticker: str, d: Dict[str, Any]) -> 'StockData':
        """
        Build from a raw dict, filling missing parts and normalizing histories.

        Parameters
        ----------
        ticker : str
            Ticker symbol (e.g., '7203.T').
        d : Dict[str, Any]
            Raw data with any of 'info', 'fast_info' and the frame keys.

        Returns
        -------
        StockData
            Data with empty defaults and tz-naive history indexes.
        """
        frames = {k: d.get(k) if d.get(k) is not None else pd.DataFrame() for k in _FRAMES}
        for key in ('history', 'history_monthly'):
            frames[key] = _to_naive_datetime_index(frames[key])
        return cls(ticker, d.get('info') or {}, d.get('fast_info') or {}, **frames)
