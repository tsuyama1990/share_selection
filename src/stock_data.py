"""Typed container for one ticker's raw data (the only place that knows its shape)."""

import contextlib
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

_FRAMES = ("financials", "balance_sheet", "cashflow", "history", "history_monthly", "quarterly_income")


def _to_naive_datetime_index(df: pd.DataFrame, market_tz: str) -> pd.DataFrame:
    """Naive datetime index; a tz-aware one is converted to ``market_tz`` first (15:00 UTC can be the next JST day)."""
    if df.empty:
        return df
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        with contextlib.suppress(ValueError, TypeError):
            df.index = pd.to_datetime(df.index)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert(market_tz).normalize().tz_localize(None)
    return df


@dataclass(frozen=True)
class StockData:
    """Raw data of one ticker. Statements: line items x periods (latest first); histories: indexed by date."""

    ticker: str
    info: dict[str, Any] = field(default_factory=dict)
    fast_info: dict[str, Any] = field(default_factory=dict)
    financials: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_sheet: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow: pd.DataFrame = field(default_factory=pd.DataFrame)
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    history_monthly: pd.DataFrame = field(default_factory=pd.DataFrame)
    quarterly_income: pd.DataFrame = field(default_factory=pd.DataFrame)

    @classmethod
    def from_dict(cls, ticker: str, d: dict[str, Any], market_tz: str) -> "StockData":
        """Build from a raw dict: missing parts become empty, history indexes become naive dates."""
        frames: dict[str, pd.DataFrame] = {k: d[k] if d.get(k) is not None else pd.DataFrame() for k in _FRAMES}
        for key in ("history", "history_monthly"):
            frames[key] = _to_naive_datetime_index(frames[key], market_tz)
        return cls(ticker, d.get("info") or {}, d.get("fast_info") or {}, **frames)

    @property
    def latest_balance_sheet(self) -> pd.Series | None:
        return None if self.balance_sheet.empty else self.balance_sheet.iloc[:, 0]

    @property
    def latest_cashflow(self) -> pd.Series | None:
        return None if self.cashflow.empty else self.cashflow.iloc[:, 0]
