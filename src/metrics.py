"""Pure, config-free helpers for reading yfinance data."""
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd

# Japanese equity ratio (自己資本比率) excludes non-controlling interests,
# so the parent's equity comes first.
EQUITY_KEYS = ('Stockholders Equity', 'Total Stockholder Equity', 'Total Equity Gross Minority Interest')
CASH_KEYS = ('Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments')
DEBT_KEYS = ('Total Debt',)
OCF_KEYS = ('Operating Cash Flow', 'Total Cash From Operating Activities')
ICF_KEYS = ('Investing Cash Flow', 'Total Cashflows From Investing Activities')
FCF_KEYS = ('Financing Cash Flow', 'Total Cash From Financing Activities')


def to_num(value: Any) -> Optional[float]:
    """
    Convert a value to float, treating None/NaN/non-numeric as missing.

    Parameters
    ----------
    value : Any
        Raw value from yfinance (may be None, NaN, or a number).

    Returns
    -------
    Optional[float]
        The value as float, or None if missing.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(value) else value


def first_valid(row: pd.Series, keys: Tuple[str, ...]) -> Optional[float]:
    """
    Return the first non-missing value among keys.

    Unlike ``a or b``, a NaN in an earlier key does not shadow later keys.

    Parameters
    ----------
    row : pd.Series
        A single period of a financial statement.
    keys : Tuple[str, ...]
        Line item names in priority order.

    Returns
    -------
    Optional[float]
        The first valid value, or None if all are missing.
    """
    for key in keys:
        value = to_num(row.get(key))
        if value is not None:
            return value
    return None


def latest_valid_period(df: pd.DataFrame, keys: Tuple[str, ...]) -> Optional[int]:
    """
    Position of the most recent period where all keys have values.

    yfinance sometimes adds a column for a fiscal year that has not been
    reported yet (all NaN); that column is skipped.

    Parameters
    ----------
    df : pd.DataFrame
        Financial statement (latest period first).
    keys : Tuple[str, ...]
        Line items that must all be present.

    Returns
    -------
    Optional[int]
        Column position, or None if no period has all keys.
    """
    if not set(keys) <= set(df.index):
        return None
    for i in range(df.shape[1]):
        if all(to_num(df[df.columns[i]].get(key)) is not None for key in keys):
            return i
    return None


def sales_cagr(
    financials: pd.DataFrame,
    years_back: int = 4,
    min_years: int = 3
) -> Tuple[Optional[float], Optional[int]]:
    """
    Calculate annualized sales growth (CAGR) over up to N years.

    yfinance usually returns 4-5 annual periods and the oldest is often NaN,
    so the span is the oldest valid period within ``years_back``. Annualizing
    makes 3-year and 4-year spans comparable.

    Parameters
    ----------
    financials : pd.DataFrame
        Financials DataFrame containing 'Total Revenue' (latest period first).
    years_back : int, optional
        Maximum number of years to look back, by default 4.
    min_years : int, optional
        Minimum span required, by default 3.

    Returns
    -------
    Tuple[Optional[float], Optional[int]]
        (cagr, years). Returns (None, None) if insufficient data.
    """
    latest = latest_valid_period(financials, ('Total Revenue',))
    if latest is None:
        return None, None
    sales = financials.loc['Total Revenue'].iloc[latest:]

    current_sales = to_num(sales.iloc[0])
    if current_sales is None or current_sales <= 0:
        return None, None

    for years in range(min(years_back, len(sales) - 1), min_years - 1, -1):
        past_sales = to_num(sales.iloc[years])
        if past_sales is not None and past_sales > 0:
            cagr = (current_sales / past_sales) ** (1 / years) - 1
            return cagr, years

    return None, None


def avg_turnover(hist_daily: Optional[pd.DataFrame], days: int = 60) -> Optional[float]:
    """
    Average daily trading value (Close x Volume) over the last N sessions.

    Parameters
    ----------
    hist_daily : Optional[pd.DataFrame]
        Daily history with 'Close' and 'Volume' columns.
    days : int, optional
        Number of recent sessions to average, by default 60.

    Returns
    -------
    Optional[float]
        Average daily turnover in JPY, or None if unavailable.
    """
    if hist_daily is None or hist_daily.empty or not {'Close', 'Volume'} <= set(hist_daily.columns):
        return None
    turnover = (hist_daily['Close'] * hist_daily['Volume']).dropna().tail(days)
    return to_num(turnover.mean()) if len(turnover) else None
