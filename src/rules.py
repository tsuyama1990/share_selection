"""Gatekeeper rules: cheap pass/fail filters run before scoring.

A metric a rule depends on but cannot compute (missing or NaN) fails the
rule, so incomplete data never slips through. Thresholds are injected via
dataclass fields; use :func:`build_rules` to create rules from config.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Protocol

from .metrics import (
    EQUITY_KEYS, FCF_KEYS, ICF_KEYS, OCF_KEYS,
    avg_turnover, first_valid, latest_valid_period, to_num,
)
from .stock_data import StockData


class RuleResult(NamedTuple):
    """Outcome of a rule: whether it passed and the metrics it computed."""

    passed: bool
    metrics: Dict[str, Any]


def _fail() -> RuleResult:
    """Return a failed result."""
    return RuleResult(False, {})


class Rule(Protocol):
    """A gatekeeper rule. ``metrics`` holds earlier rules' output (read-only)."""

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Evaluate the rule for one stock."""
        ...


def _sales_and_income(data: StockData):
    """Return (sales, operating income) of the latest valid period, or None."""
    fin = data.financials
    i = latest_valid_period(fin, ('Total Revenue', 'Operating Income'))
    if i is None:
        return None
    return to_num(fin.loc['Total Revenue'].iloc[i]), to_num(fin.loc['Operating Income'].iloc[i])


@dataclass
class MarketCapRule:
    """Market cap >= ``min_cap``; emits price and market cap."""

    min_cap: float

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Check market cap."""
        mcap = to_num(data.fast_info.get('market_cap'))
        if mcap is None or mcap < self.min_cap:
            return _fail()
        return RuleResult(True, {
            'Current_Price': to_num(data.fast_info.get('last_price')),
            'Market_Cap': mcap,
            'Market_Cap(Billion)': round(mcap / 1e9, 2),
        })


@dataclass
class LiquidityRule:
    """Average daily turnover over ``days`` sessions >= ``min_turnover`` JPY (0 disables)."""

    min_turnover: float
    days: int

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Check liquidity; always emits the turnover when computable."""
        turnover = avg_turnover(data.history, self.days)
        out = {'Avg_Turnover(M JPY)': round(turnover / 1e6, 1) if turnover is not None else None}
        if self.min_turnover > 0 and (turnover is None or turnover < self.min_turnover):
            return _fail()
        return RuleResult(True, out)


@dataclass
class EquityRatioRule:
    """Equity ratio (Stockholders' Equity / Total Assets) >= ``min_ratio``."""

    min_ratio: float

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Check equity ratio of the latest balance sheet."""
        if data.balance_sheet.empty:
            return _fail()
        latest = data.balance_sheet.iloc[:, 0]
        assets = to_num(latest.get('Total Assets'))
        equity = first_valid(latest, EQUITY_KEYS)
        if assets is None or assets <= 0 or equity is None:
            return _fail()
        ratio = equity / assets
        return RuleResult(ratio >= self.min_ratio, {'Equity_Ratio': round(ratio * 100, 2)})


@dataclass
class OperatingMarginRule:
    """Operating margin >= ``min_margin`` (latest period with sales and income)."""

    min_margin: float

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Check operating margin."""
        found = _sales_and_income(data)
        if found is None or found[0] <= 0:
            return _fail()
        margin = found[1] / found[0]
        return RuleResult(margin >= self.min_margin, {'Operating_Margin(%)': round(margin * 100, 2)})


@dataclass
class PsrRule:
    """PSR (Market_Cap / sales) <= ``cap``; needs Market_Cap in metrics."""

    cap: float

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Check PSR."""
        found = _sales_and_income(data)
        if found is None or found[0] <= 0:
            return _fail()
        psr = metrics['Market_Cap'] / found[0]
        return RuleResult(psr <= self.cap, {'PSR': round(psr, 2)})


@dataclass
class OperatingCashFlowRule:
    """Operating cash flow > ``min_ocf``; emits OCF/ICF/FCF."""

    min_ocf: float

    def evaluate(self, data: StockData, metrics: Dict[str, Any]) -> RuleResult:
        """Check operating cash flow of the latest period."""
        if data.cashflow.empty:
            return _fail()
        latest = data.cashflow.iloc[:, 0]
        ocf = first_valid(latest, OCF_KEYS)
        if ocf is None or ocf <= self.min_ocf:
            return _fail()
        return RuleResult(True, {
            'Operating_Cash_Flow': ocf,
            'Investing_Cash_Flow': first_valid(latest, ICF_KEYS),
            'Financing_Cash_Flow': first_valid(latest, FCF_KEYS),
        })


def build_rules(cfg: Dict[str, Any]) -> List[Rule]:
    """
    Build the gatekeeper rules, in evaluation order, from ``config['gatekeeper']``.

    Parameters
    ----------
    cfg : Dict[str, Any]
        Full configuration (uses the 'gatekeeper' section).

    Returns
    -------
    List[Rule]
        Rules to run in order.
    """
    gk = cfg['gatekeeper']
    return [
        MarketCapRule(gk['market_cap_min']),
        LiquidityRule(gk['turnover_min'], gk['turnover_days']),
        EquityRatioRule(gk['equity_ratio_min']),
        OperatingMarginRule(gk['operating_margin_min']),
        PsrRule(gk['psr_cap']),
        OperatingCashFlowRule(gk['operating_cash_flow_min']),
    ]
