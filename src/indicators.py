"""Indicators: each reports metrics for the result row from the stock data and earlier metrics."""

from dataclasses import dataclass
from typing import Any, Protocol

from . import fields as F
from .metrics import (
    CASH_KEYS,
    DEBT_KEYS,
    EQUITY_KEYS,
    first_valid,
    latest_values,
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
        return {F.SALES_CAGR: round(cagr * 100, 2), F.SALES_GROWTH_YEARS: years}


class CashRatio:
    """Cash / market cap."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        latest_bs = data.latest_balance_sheet
        cash = None if latest_bs is None else first_valid(latest_bs, CASH_KEYS)
        mcap = metrics.get(F.MARKET_CAP)
        if cash is None or mcap is None or mcap <= 0:
            return {}
        return {F.CASH_TO_MARKET_CAP: round(cash / mcap, 2)}


class NetCash:
    """Net cash and Real_PSR = (Market_Cap - net cash) / sales. Missing debt counts as 0."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        latest_bs = data.latest_balance_sheet
        cash = None if latest_bs is None else first_valid(latest_bs, CASH_KEYS)
        if latest_bs is None or cash is None:
            return {}
        debt = first_valid(latest_bs, DEBT_KEYS) or 0.0
        net_cash = cash - debt
        out = {F.NET_CASH: round(net_cash / 1e9, 2)}
        found = latest_values(data.financials, ("Total Revenue",))
        sales = None if found is None else found[0]
        mcap = metrics.get(F.MARKET_CAP)
        if sales is not None and sales > 0 and mcap is not None:
            out[F.REAL_PSR] = round((mcap - net_cash) / sales, 2)
        return out


class Pbr:
    """F.PBR (info first, else Market_Cap / equity)."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        pbr = to_num(data.info.get("priceToBook"))
        latest_bs = data.latest_balance_sheet
        if pbr is None and latest_bs is not None:
            equity = first_valid(latest_bs, EQUITY_KEYS)
            mcap = metrics.get(F.MARKET_CAP)
            if equity is not None and equity > 0 and mcap is not None:
                pbr = mcap / equity
        return {} if pbr is None else {F.PBR: round(pbr, 2)}


class DividendYield:
    """Forward dividend yield, falling back to trailing."""

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        # dividendYield is a percent (3.0 = 3%); trailingAnnualDividendYield is a fraction
        pct = to_num(data.info.get("dividendYield"))
        div = pct / 100 if pct is not None else to_num(data.info.get("trailingAnnualDividendYield"))
        return {} if div is None else {F.DIVIDEND_YIELD: round(div * 100, 2)}


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
        out = {F.ma(self.ma_short): round(ma_s, 1), F.ma(self.ma_long): round(ma_l, 1)}
        price = metrics.get(F.CURRENT_PRICE)
        if price is None:
            return out
        if price > ma_s > ma_l:
            out[F.CHART_TREND] = "Strong Bull"
        elif price > ma_s:
            out[F.CHART_TREND] = "Bull"
        else:
            out[F.CHART_TREND] = "Bear"
        return out


@dataclass
class ShockLow:
    """Downside from the current price to the lowest monthly low of past crashes."""

    windows: dict[str, tuple[str, str]]  # name -> (start, end) dates

    def compute(self, data: StockData, metrics: dict[str, Any]) -> dict[str, Any]:
        hist = data.history_monthly
        price = to_num(metrics.get(F.CURRENT_PRICE))
        out: dict[str, Any] = {}
        if hist.empty or "Low" not in hist.columns or price is None or price <= 0:
            return out
        for name, (start, end) in self.windows.items():
            low = to_num(hist.loc[start:end, "Low"].min())
            if low is not None:
                out[F.downside_to_low(name)] = round((low / price - 1) * 100, 1)
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
