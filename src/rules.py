"""Gatekeeper rules: pass/fail filters. Every rule reports the metrics it can compute even when it fails; a metric
that cannot be computed fails its rule."""

from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

from . import fields as F
from .metrics import (
    EQUITY_KEYS,
    FCF_KEYS,
    ICF_KEYS,
    OCF_KEYS,
    avg_turnover,
    first_valid,
    latest_values,
    to_num,
)
from .stock_data import StockData


class RuleResult(NamedTuple):
    """Outcome of a rule: whether it passed and the metrics it computed."""

    passed: bool
    metrics: dict[str, Any]


_FAIL = RuleResult(False, {})


class Rule(Protocol):
    """A gatekeeper rule. ``metrics`` holds earlier rules' output (read-only; may lack keys of failed rules)."""

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult: ...


SALES_AND_INCOME_KEYS = ("Total Revenue", "Operating Income")


@dataclass
class MarketCapRule:
    """Market cap >= ``min_cap``; emits price and market cap."""

    min_cap: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult:
        mcap = to_num(data.fast_info.get("market_cap"))
        out = {F.CURRENT_PRICE: to_num(data.fast_info.get("last_price"))}
        if mcap is not None:
            out[F.MARKET_CAP] = mcap
        return RuleResult(mcap is not None and mcap >= self.min_cap, out)


@dataclass
class LiquidityRule:
    """Average daily turnover over ``days`` sessions >= ``min_turnover`` JPY (0 disables)."""

    min_turnover: float
    days: int

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult:
        turnover = avg_turnover(data.history, self.days)
        out = {F.AVG_TURNOVER: round(turnover / 1e6, 1) if turnover is not None else None}
        too_thin = self.min_turnover > 0 and (turnover is None or turnover < self.min_turnover)
        return RuleResult(not too_thin, out)


@dataclass
class EquityRatioRule:
    """Equity ratio (Stockholders' Equity / Total Assets) >= ``min_ratio``."""

    min_ratio: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult:
        latest = data.latest_balance_sheet
        if latest is None:
            return _FAIL
        assets = to_num(latest.get("Total Assets"))
        equity = first_valid(latest, EQUITY_KEYS)
        if assets is None or assets <= 0 or equity is None:
            return _FAIL
        ratio = equity / assets
        return RuleResult(ratio >= self.min_ratio, {F.EQUITY_RATIO: round(ratio * 100, 2)})


@dataclass
class OperatingMarginRule:
    """Operating margin >= ``min_margin`` (latest period with sales and income)."""

    min_margin: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult:
        found = latest_values(data.financials, SALES_AND_INCOME_KEYS)
        if found is None or found[0] <= 0:
            return _FAIL
        margin = found[1] / found[0]
        return RuleResult(margin >= self.min_margin, {F.OPERATING_MARGIN: round(margin * 100, 2)})


@dataclass
class PsrRule:
    """F.PSR (Market_Cap / sales) <= ``cap``; fails without Market_Cap in metrics."""

    cap: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult:
        found = latest_values(data.financials, SALES_AND_INCOME_KEYS)
        mcap = metrics.get(F.MARKET_CAP)
        if found is None or found[0] <= 0 or mcap is None:
            return _FAIL
        psr = mcap / found[0]
        return RuleResult(psr <= self.cap, {F.PSR: round(psr, 2)})


@dataclass
class OperatingCashFlowRule:
    """Operating cash flow > ``min_ocf``; emits OCF/ICF/FCF."""

    min_ocf: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> RuleResult:
        latest = data.latest_cashflow
        if latest is None:
            return _FAIL
        ocf = first_valid(latest, OCF_KEYS)
        return RuleResult(
            ocf is not None and ocf > self.min_ocf,
            {
                F.OPERATING_CASH_FLOW: ocf,
                F.INVESTING_CASH_FLOW: first_valid(latest, ICF_KEYS),
                F.FINANCING_CASH_FLOW: first_valid(latest, FCF_KEYS),
            },
        )


def build_rules(cfg: dict[str, Any]) -> list[Rule]:
    """Build the rules, in evaluation order, from ``cfg['gatekeeper']``."""
    gk = cfg["gatekeeper"]
    return [
        MarketCapRule(gk["market_cap_min"]),
        LiquidityRule(gk["turnover_min"], gk["turnover_days"]),
        EquityRatioRule(gk["equity_ratio_min"]),
        OperatingMarginRule(gk["operating_margin_min"]),
        PsrRule(gk["psr_cap"]),
        OperatingCashFlowRule(gk["operating_cash_flow_min"]),
    ]
