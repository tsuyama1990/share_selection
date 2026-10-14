"""Indicators: each reports metrics for the result row from the stock data and earlier metrics."""

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from .metrics import (
    CASH_KEYS,
    DEBT_KEYS,
    EQUITY_KEYS,
    first_valid,
    latest_valid_period,
    sales_cagr,
    to_num,
)
from .stock_data import StockData


class Indicator(Protocol):
    """A metric provider. ``metrics`` holds gatekeeper output (read-only)."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class SalesCagr:
    """Sales CAGR over ``min_years``..``years_back``."""

    years_back: int
    min_years: int

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        cagr, years = sales_cagr(data.financials, self.years_back, self.min_years)
        if cagr is None:
            return {}
        return {"Sales_CAGR(%)": round(cagr * 100, 2), "Sales_Growth_Years": years}


def _latest_balance_sheet(data: StockData) -> pd.Series | None:
    return None if data.balance_sheet.empty else data.balance_sheet.iloc[:, 0]


class CashRatio:
    """Cash / market cap."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        latest_bs = _latest_balance_sheet(data)
        cash = None if latest_bs is None else first_valid(latest_bs, CASH_KEYS)
        mcap = metrics.get("Market_Cap")
        if cash is None or mcap is None or mcap <= 0:
            return {}
        return {"Cash_to_MarketCap_Ratio": round(cash / mcap, 2)}


class NetCash:
    """Net cash and Real_PSR = (Market_Cap - net cash) / sales. Missing debt counts as 0."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        latest_bs = _latest_balance_sheet(data)
        cash = None if latest_bs is None else first_valid(latest_bs, CASH_KEYS)
        if latest_bs is None or cash is None:
            return {}
        debt = first_valid(latest_bs, DEBT_KEYS) or 0.0
        net_cash = cash - debt
        out = {"Net_Cash(Billion)": round(net_cash / 1e9, 2)}
        fin = data.financials
        i = latest_valid_period(fin, ("Total Revenue",))
        sales = None if i is None else to_num(fin.loc["Total Revenue"].iloc[i])
        mcap = metrics.get("Market_Cap")
        if sales is not None and sales > 0 and mcap is not None:
            out["Real_PSR"] = round((mcap - net_cash) / sales, 2)
        return out


class Pbr:
    """PBR (info first, else Market_Cap / equity)."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        pbr = to_num(data.info.get("priceToBook"))
        latest_bs = _latest_balance_sheet(data)
        if pbr is None and latest_bs is not None:
            equity = first_valid(latest_bs, EQUITY_KEYS)
            mcap = metrics.get("Market_Cap")
            if equity is not None and equity > 0 and mcap is not None:
                pbr = mcap / equity
        return {} if pbr is None else {"PBR": round(pbr, 2)}


class DividendYield:
    """Forward dividend yield, falling back to trailing."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        # dividendYield is a percent (3.0 = 3%); trailingAnnualDividendYield is a fraction
        pct = to_num(data.info.get("dividendYield"))
        div = pct / 100 if pct is not None else to_num(data.info.get("trailingAnnualDividendYield"))
        return {} if div is None else {"Dividend_Yield(%)": round(div * 100, 2)}


@dataclass
class Trend:
    """Monthly MA trend: Strong Bull (price > MA short > MA long), Bull (price > MA short), else Bear."""

    ma_short: int
    ma_long: int

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        hist = data.history_monthly
        if hist.empty or len(hist) < self.ma_long:
            return {}
        close = hist["Close"]
        ma_s = close.rolling(self.ma_short).mean().iloc[-1]
        ma_l = close.rolling(self.ma_long).mean().iloc[-1]
        out = {"MA12": round(ma_s, 1), "MA24": round(ma_l, 1)}
        price = metrics.get("Current_Price")
        if price is None:
            return out
        if price > ma_s > ma_l:
            out["Chart_Trend"] = "Strong Bull"
        elif price > ma_s:
            out["Chart_Trend"] = "Bull"
        else:
            out["Chart_Trend"] = "Bear"
        return out


@dataclass
class ShockLow:
    """Downside from the current price to the lowest monthly low of past crashes."""

    windows: dict[str, tuple[str, str]]  # name -> (start, end) dates

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        hist = data.history_monthly
        price = to_num(metrics.get("Current_Price"))
        out: dict[str, Any] = {}
        if hist.empty or "Low" not in hist.columns or price is None or price <= 0:
            return out
        for name, (start, end) in self.windows.items():
            low = to_num(hist.loc[start:end, "Low"].min())
            if low is not None:
                out[f"Downside_to_{name}_Low(%)"] = round((low / price - 1) * 100, 1)
        return out


def build_indicators(cfg: dict[str, Any]) -> list[Indicator]:
    """Build the indicators, in evaluation order, from ``cfg['indicators']``."""
    sc = cfg["indicators"]
    return [
        SalesCagr(sc["sales_cagr_years_back"], sc["sales_cagr_min_years"]),
        CashRatio(),
        NetCash(),
        Pbr(),
        DividendYield(),
        Trend(sc["ma_short"], sc["ma_long"]),
        ShockLow({name.capitalize(): (start, end) for name, (start, end) in sc["shock_lows"].items()}),
    ]
