"""Scorers: each criterion awards points to one category and reports metrics."""

from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

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


class ScoreResult(NamedTuple):
    """Points for a category ('Growth' | 'Value' | 'Safety') and reported metrics."""

    category: str
    points: int
    metrics: dict[str, Any]
    recommendation: str | None = None  # forced recommendation type (NET-NET)


class Scorer(Protocol):
    """A scoring criterion. ``metrics`` holds gatekeeper output (read-only)."""

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult: ...


@dataclass
class SalesGrowthScorer:
    """Growth points if sales CAGR >= ``threshold`` (span: ``min_years``..``years_back``)."""

    threshold: float
    points: int
    years_back: int
    min_years: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        cagr, years = sales_cagr(data.financials, self.years_back, self.min_years)
        if cagr is None:
            return ScoreResult("Growth", 0, {})
        out = {"Sales_CAGR(%)": round(cagr * 100, 2), "Sales_Growth_Years": years}
        return ScoreResult("Growth", self.points if cagr >= self.threshold else 0, out)


def _latest_balance_sheet(data: StockData) -> pd.Series | None:
    return None if data.balance_sheet.empty else data.balance_sheet.iloc[:, 0]


@dataclass
class PsrScorer:
    """Value points by PSR tier (<= super_cheap, <= cheap, else fair); uses Real_PSR when reported, else PSR."""

    super_cheap: float
    super_cheap_points: int
    cheap: float
    cheap_points: int
    fair_points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        psr = metrics.get("Real_PSR", metrics.get("PSR"))
        if psr is None:
            return ScoreResult("Value", 0, {})
        if psr <= self.super_cheap:
            pts = self.super_cheap_points
        elif psr <= self.cheap:
            pts = self.cheap_points
        else:
            pts = self.fair_points
        return ScoreResult("Value", pts, {})


@dataclass
class CashRatioScorer:
    """Bonus and NET-NET recommendation if cash >= ``net_net_ratio`` x market cap."""

    bonus: int
    net_net_ratio: float

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        latest_bs = _latest_balance_sheet(data)
        cash = None if latest_bs is None else first_valid(latest_bs, CASH_KEYS)
        mcap = metrics.get("Market_Cap")
        if cash is None or mcap is None or mcap <= 0:
            return ScoreResult("Value", 0, {})
        ratio = cash / mcap
        out = {"Cash_to_MarketCap_Ratio": round(ratio, 2)}
        if ratio >= self.net_net_ratio:
            return ScoreResult("Value", self.bonus, out, "NET-NET")
        return ScoreResult("Value", 0, out)


@dataclass
class NetCashScorer:
    """Value points if net cash > 0; reports Real_PSR = (Market_Cap - net cash) / sales. Missing debt counts as 0."""

    points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        latest_bs = _latest_balance_sheet(data)
        cash = None if latest_bs is None else first_valid(latest_bs, CASH_KEYS)
        if latest_bs is None or cash is None:
            return ScoreResult("Value", 0, {})
        debt = first_valid(latest_bs, DEBT_KEYS) or 0.0
        net_cash = cash - debt
        out = {"Net_Cash(Billion)": round(net_cash / 1e9, 2)}
        fin = data.financials
        i = latest_valid_period(fin, ("Total Revenue",))
        sales = None if i is None else to_num(fin.loc["Total Revenue"].iloc[i])
        mcap = metrics.get("Market_Cap")
        if sales is not None and sales > 0 and mcap is not None:
            out["Real_PSR"] = round((mcap - net_cash) / sales, 2)
        return ScoreResult("Value", self.points if net_cash > 0 else 0, out)


@dataclass
class PbrScorer:
    """Value points if PBR < ``cheap`` (info first, else Market_Cap / equity)."""

    cheap: float
    points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        pbr = to_num(data.info.get("priceToBook"))
        latest_bs = _latest_balance_sheet(data)
        if pbr is None and latest_bs is not None:
            equity = first_valid(latest_bs, EQUITY_KEYS)
            mcap = metrics.get("Market_Cap")
            if equity is not None and equity > 0 and mcap is not None:
                pbr = mcap / equity
        if pbr is None:
            return ScoreResult("Value", 0, {})
        return ScoreResult("Value", self.points if pbr < self.cheap else 0, {"PBR": round(pbr, 2)})


@dataclass
class DividendScorer:
    """Value points if dividend yield >= ``target`` (fraction)."""

    target: float
    points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        # dividendYield is a percent (3.0 = 3%); trailingAnnualDividendYield is a fraction
        pct = to_num(data.info.get("dividendYield"))
        div = pct / 100 if pct is not None else to_num(data.info.get("trailingAnnualDividendYield"))
        if div is None:
            return ScoreResult("Value", 0, {})
        return ScoreResult(
            "Value", self.points if div >= self.target else 0, {"Dividend_Yield(%)": round(div * 100, 2)}
        )


@dataclass
class PerGrowthScorer:
    """Value points if forward PE < trailing PE (both positive)."""

    points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        f_pe = to_num(data.info.get("forwardPE"))
        t_pe = to_num(data.info.get("trailingPE"))
        if f_pe is None or t_pe is None or f_pe <= 0 or t_pe <= 0:
            return ScoreResult("Value", 0, {})
        return ScoreResult("Value", self.points if f_pe < t_pe else 0, {})


@dataclass
class TrendScorer:
    """Safety points from the monthly MA trend (Strong Bull: ``points``, Bull: ``bull_points``)."""

    ma_short: int
    ma_long: int
    points: int
    bull_points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        hist = data.history_monthly
        if hist.empty or len(hist) < self.ma_long:
            return ScoreResult("Safety", 0, {})
        close = hist["Close"]
        ma_s = close.rolling(self.ma_short).mean().iloc[-1]
        ma_l = close.rolling(self.ma_long).mean().iloc[-1]
        out = {"MA12": round(ma_s, 1), "MA24": round(ma_l, 1)}
        price = metrics.get("Current_Price")
        if price is None:
            return ScoreResult("Safety", 0, out)
        if price > ma_s > ma_l:
            out["Chart_Trend"], pts = "Strong Bull", self.points
        elif price > ma_s:
            out["Chart_Trend"], pts = "Bull", self.bull_points
        else:
            out["Chart_Trend"], pts = "Bear", 0
        return ScoreResult("Safety", pts, out)


@dataclass
class EquityScorer:
    """Safety points if Equity_Ratio (percent, from the gatekeeper) >= ``ideal`` (fraction)."""

    ideal: float
    points: int

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        ratio = to_num(metrics.get("Equity_Ratio"))
        ok = ratio is not None and ratio >= self.ideal * 100
        return ScoreResult("Safety", self.points if ok else 0, {})


@dataclass
class ShockLowMetric:
    """Reports the downside from the current price to the lowest monthly low of past crashes; no points."""

    windows: dict[str, tuple[str, str]]  # name -> (start, end) dates

    def score(self, data: StockData, metrics: dict[str, Any]) -> ScoreResult:
        hist = data.history_monthly
        price = to_num(metrics.get("Current_Price"))
        out: dict[str, Any] = {}
        if hist.empty or "Low" not in hist.columns or price is None or price <= 0:
            return ScoreResult("Safety", 0, out)
        for name, (start, end) in self.windows.items():
            low = to_num(hist.loc[start:end, "Low"].min())
            if low is not None:
                out[f"Downside_to_{name}_Low(%)"] = round((low / price - 1) * 100, 1)
        return ScoreResult("Safety", 0, out)


def build_scorers(cfg: dict[str, Any]) -> list[Scorer]:
    """Build the scorers, in evaluation order, from ``cfg['scoring']``."""
    sc = cfg["scoring"]
    return [
        SalesGrowthScorer(
            sc["sales_cagr_threshold"],
            sc["sales_growth_points"],
            sc["sales_cagr_years_back"],
            sc["sales_cagr_min_years"],
        ),
        CashRatioScorer(sc["net_net_bonus"], sc["net_net_ratio"]),
        NetCashScorer(sc["net_cash_points"]),  # before PsrScorer: provides Real_PSR
        PsrScorer(
            sc["psr_super_cheap"],
            sc["psr_super_cheap_points"],
            sc["psr_cheap"],
            sc["psr_cheap_points"],
            sc["psr_fair_points"],
        ),
        PbrScorer(sc["pbr_cheap"], sc["pbr_points"]),
        DividendScorer(sc["dividend_yield_target"], sc["dividend_points"]),
        PerGrowthScorer(sc["per_growth_points"]),
        EquityScorer(sc["equity_ratio_ideal"], sc["equity_ideal_points"]),
        TrendScorer(sc["ma_short"], sc["ma_long"], sc["technical_points"], sc["bull_points"]),
        ShockLowMetric({name.capitalize(): (start, end) for name, (start, end) in sc["shock_lows"].items()}),
    ]
