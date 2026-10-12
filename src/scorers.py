"""Scorers: each criterion awards points to one category and reports metrics.

Thresholds and points are injected via dataclass fields; use
:func:`build_scorers` to create scorers from config.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional, Protocol

from .metrics import EQUITY_KEYS, LIABILITY_KEYS, first_valid, sales_cagr, to_num
from .stock_data import StockData


class ScoreResult(NamedTuple):
    """Points for a category ('Growth' | 'Value' | 'Safety') and reported metrics."""

    category: str
    points: int
    metrics: Dict[str, Any]
    recommendation: Optional[str] = None  # forced recommendation type (NET-NET)


class Scorer(Protocol):
    """A scoring criterion. ``metrics`` holds gatekeeper output (read-only)."""

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score one stock."""
        ...


@dataclass
class SalesGrowthScorer:
    """Growth points if sales CAGR >= ``threshold``."""

    threshold: float
    points: int
    years_back: int = 4

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score sales CAGR."""
        cagr, years = sales_cagr(data.financials, self.years_back)
        if cagr is None:
            return ScoreResult('Growth', 0, {})
        out = {'Sales_CAGR(%)': round(cagr * 100, 2), 'Sales_Growth_Years': years}
        return ScoreResult('Growth', self.points if cagr >= self.threshold else 0, out)


@dataclass
class PsrScorer:
    """Value points: ``cheap_points`` if PSR <= ``super_cheap``, else ``fair_points``."""

    super_cheap: float
    cheap_points: int
    fair_points: int

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score PSR (from gatekeeper metrics)."""
        cheap = metrics['PSR'] <= self.super_cheap
        return ScoreResult('Value', self.cheap_points if cheap else self.fair_points, {})


@dataclass
class NetNetScorer:
    """
    Net-Net (Graham): bonus and NET-NET recommendation if net current asset
    value (current assets - total liabilities) >= market cap.
    """

    bonus: int

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score NCAV to market cap ratio."""
        latest_bs = data.balance_sheet.iloc[:, 0]
        current_assets = to_num(latest_bs.get('Current Assets'))
        liabilities = first_valid(latest_bs, LIABILITY_KEYS)
        mcap = metrics['Market_Cap']
        if current_assets is None or liabilities is None or mcap <= 0:
            return ScoreResult('Value', 0, {})
        ratio = (current_assets - liabilities) / mcap
        out = {'NCAV_to_MarketCap_Ratio': round(ratio, 2)}
        if ratio >= 1.0:
            out['Net_Net_Flag(T/F)'] = True
            return ScoreResult('Value', self.bonus, out, 'NET-NET')
        return ScoreResult('Value', 0, out)


@dataclass
class PbrMetric:
    """Reports PBR (info first, else Market_Cap / equity); awards no points."""

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Report PBR."""
        pbr = to_num(data.info.get('priceToBook'))
        if pbr is None:
            equity = first_valid(data.balance_sheet.iloc[:, 0], EQUITY_KEYS)
            if equity is not None and equity > 0:
                pbr = metrics['Market_Cap'] / equity
        return ScoreResult('Value', 0, {} if pbr is None else {'PBR': round(pbr, 2)})


@dataclass
class DividendScorer:
    """Value points if dividend yield >= ``target`` (fraction)."""

    target: float
    points: int

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score dividend yield.

        trailingAnnualDividendYield is a fraction (0.03 = 3%), while yfinance's
        dividendYield is already in percent (3.0 = 3%) and only a fallback.
        """
        div = to_num(data.info.get('trailingAnnualDividendYield'))
        if div is None:
            pct = to_num(data.info.get('dividendYield'))
            div = pct / 100 if pct is not None else None
        if div is None:
            return ScoreResult('Value', 0, {})
        return ScoreResult('Value', self.points if div >= self.target else 0,
                           {'Dividend_Yield(%)': round(div * 100, 2)})


@dataclass
class PerGrowthScorer:
    """Value points if forward PE < trailing PE (both positive)."""

    points: int

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score PER growth."""
        f_pe = to_num(data.info.get('forwardPE'))
        t_pe = to_num(data.info.get('trailingPE'))
        if f_pe is None or t_pe is None or f_pe <= 0 or t_pe <= 0:
            return ScoreResult('Value', 0, {})
        out = {'Forward_PE': round(f_pe, 2), 'Trailing_PE': round(t_pe, 2)}
        if f_pe < t_pe:
            out['PE_Growth_Flag(T/F)'] = True
            return ScoreResult('Value', self.points, out)
        return ScoreResult('Value', 0, out)


@dataclass
class TrendScorer:
    """Safety points from the monthly MA trend (Strong Bull: ``points``, Bull: 1)."""

    ma_short: int
    ma_long: int
    points: int

    def score(self, data: StockData, metrics: Dict[str, Any]) -> ScoreResult:
        """Score the monthly chart trend."""
        hist = data.history_monthly
        if hist.empty or len(hist) < self.ma_long:
            return ScoreResult('Safety', 0, {})
        close = hist['Close']
        ma_s = close.rolling(self.ma_short).mean().iloc[-1]
        ma_l = close.rolling(self.ma_long).mean().iloc[-1]
        out = {'MA12': round(ma_s, 1), 'MA24': round(ma_l, 1)}
        price = metrics.get('Current_Price')
        if price is None:
            return ScoreResult('Safety', 0, out)
        if price > ma_s > ma_l:
            out['Chart_Trend'], pts = 'Strong Bull', self.points
        elif price > ma_s:
            out['Chart_Trend'], pts = 'Bull', 1
        else:
            out['Chart_Trend'], pts = 'Bear', 0
        return ScoreResult('Safety', pts, out)


def build_scorers(cfg: Dict[str, Any]) -> List[Scorer]:
    """
    Build the scorers from ``config['scoring']``.

    Parameters
    ----------
    cfg : Dict[str, Any]
        Full configuration (uses the 'scoring' section).

    Returns
    -------
    List[Scorer]
        Scorers to run in order.
    """
    sc = cfg['scoring']
    return [
        SalesGrowthScorer(sc['sales_cagr_threshold'], sc['sales_growth_points']),
        PsrScorer(sc['psr_super_cheap'], sc['psr_cheap_points'], sc['psr_fair_points']),
        NetNetScorer(sc['net_net_bonus']),
        PbrMetric(),
        DividendScorer(sc['dividend_yield_target'], sc['dividend_points']),
        PerGrowthScorer(sc['per_growth_points']),
        TrendScorer(sc['ma_short'], sc['ma_long'], sc['technical_points']),
    ]
