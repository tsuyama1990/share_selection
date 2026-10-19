"""Pure, config-free helpers for reading yfinance data."""

from typing import Any, cast

import numpy as np
import pandas as pd

# Japanese equity ratio (自己資本比率) excludes non-controlling interests,
# so the parent's equity comes first.
EQUITY_KEYS = ("Stockholders Equity", "Total Stockholder Equity", "Total Equity Gross Minority Interest")
CASH_KEYS = ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
DEBT_KEYS = ("Total Debt",)
OCF_KEYS = ("Operating Cash Flow", "Total Cash From Operating Activities")
ICF_KEYS = ("Investing Cash Flow", "Total Cashflows From Investing Activities")
FCF_KEYS = ("Financing Cash Flow", "Total Cash From Financing Activities")


def to_num(value: Any) -> float | None:
    """Float value, or None for None/NaN/non-numeric."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(value) else value


def first_valid(row: pd.Series, keys: tuple[str, ...]) -> float | None:
    """First non-missing value among keys (a NaN in an earlier key does not shadow later ones)."""
    for key in keys:
        value = to_num(row.get(key))
        if value is not None:
            return value
    return None


def latest_valid_period(df: pd.DataFrame, keys: tuple[str, ...]) -> int | None:
    """Column position of the latest period where all keys have values (skips unreported all-NaN years)."""
    if not set(keys) <= set(df.index):
        return None
    for i in range(df.shape[1]):
        if all(to_num(df[df.columns[i]].get(key)) is not None for key in keys):
            return i
    return None


def latest_values(df: pd.DataFrame, keys: tuple[str, ...]) -> tuple[float, ...] | None:
    """Values of ``keys`` at the latest period where all have values, or None."""
    i = latest_valid_period(df, keys)
    return None if i is None else cast(tuple[float, ...], tuple(to_num(df.loc[key].iloc[i]) for key in keys))


def sales_cagr(financials: pd.DataFrame, years_back: int, min_years: int) -> tuple[float | None, int | None]:
    """
    Annualized sales growth over the oldest valid period within ``years_back``.

    The oldest yfinance period is often NaN, so the span varies; annualizing keeps
    3- and 4-year spans comparable.

    Returns
    -------
    Tuple[Optional[float], Optional[int]]
        (cagr, years), or (None, None) if the span would be shorter than ``min_years``.
    """
    latest = latest_valid_period(financials, ("Total Revenue",))
    if latest is None:
        return None, None
    sales = financials.loc["Total Revenue"].iloc[latest:]

    current_sales = to_num(sales.iloc[0])
    if current_sales is None or current_sales <= 0:
        return None, None

    for years in range(min(years_back, len(sales) - 1), min_years - 1, -1):
        past_sales = to_num(sales.iloc[years])
        if past_sales is not None and past_sales > 0:
            cagr = (current_sales / past_sales) ** (1 / years) - 1
            return cagr, years

    return None, None


def avg_turnover(hist_daily: pd.DataFrame | None, days: int) -> float | None:
    """Average of Close x Volume over the last ``days`` sessions, or None if unavailable."""
    if hist_daily is None or hist_daily.empty or not {"Close", "Volume"} <= set(hist_daily.columns):
        return None
    turnover = (hist_daily["Close"] * hist_daily["Volume"]).dropna().tail(days)
    return to_num(turnover.mean()) if len(turnover) else None


DAYS_PER_YEAR = 365


def quarterly_eps_pair(
    quarterly_income: pd.DataFrame, tolerance_days: int
) -> tuple[float, pd.Timestamp, float | None] | None:
    """Latest quarter's Diluted EPS, its period end, and the EPS of the quarter one year earlier (within tolerance)."""
    if "Diluted EPS" not in quarterly_income.index:
        return None
    eps = quarterly_income.loc["Diluted EPS"].astype(float).dropna()
    if eps.empty:
        return None
    dates = pd.to_datetime(eps.index)
    values = eps.to_numpy()
    latest = dates.max()
    near = values[np.abs(np.asarray((latest - dates).days) - DAYS_PER_YEAR) <= tolerance_days]
    return float(values[dates == latest][0]), latest, float(near[0]) if len(near) else None


def annual_operating_change(financials: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """(operating income growth, margin change in points, operating income change) of the latest year vs the prior."""
    i = latest_valid_period(financials, ("Total Revenue", "Operating Income"))
    if i is None or i + 1 >= financials.shape[1]:
        return None, None, None
    cur, prev = financials.iloc[:, i], financials.iloc[:, i + 1]
    oi, oi_prev = to_num(cur.get("Operating Income")), to_num(prev.get("Operating Income"))
    rev, rev_prev = to_num(cur.get("Total Revenue")), to_num(prev.get("Total Revenue"))
    growth = oi / oi_prev - 1 if oi is not None and oi_prev is not None and oi_prev > 0 else None
    delta = oi - oi_prev if oi is not None and oi_prev is not None else None
    if oi is None or oi_prev is None or rev is None or rev_prev is None or rev <= 0 or rev_prev <= 0:
        return growth, None, delta
    return growth, (oi / rev - oi_prev / rev_prev) * 100, delta


def close_on_or_before(closes: pd.Series, date: pd.Timestamp) -> float | None:
    """The last close at or before ``date`` (the index may hold dates or timestamps, in any order)."""
    series = closes.dropna()
    series.index = pd.to_datetime(series.index)
    past = series[series.index <= date].sort_index()
    return float(past.iloc[-1]) if len(past) else None


def price_change(p0: float | None, p1: float | None) -> float | None:
    return None if p0 is None or p1 is None or p0 == 0 else p1 / p0 - 1


def period_return(closes: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    return price_change(close_on_or_before(closes, start), close_on_or_before(closes, end))
