"""Screener: runs gatekeeper rules, then indicators, and assembles the result row."""

from typing import Any, NamedTuple

from . import fields as F
from .improvement import ImprovementSignal
from .indicators import Indicator, build_indicators
from .quality import EpsQualityFlags
from .rules import Rule, build_rules
from .stock_data import StockData


class ScreenResult(NamedTuple):
    """Stage-1 outcome: ``row`` is the full result row if passed, else all metrics computable for the ticker."""

    passed: bool
    fail_rule: str | None
    row: dict[str, Any]


class Screener:
    """Evaluate stocks with injected rules and indicators."""

    def __init__(
        self,
        improvement: ImprovementSignal,
        quality: EpsQualityFlags,
        rules: list[Rule],
        indicators: list[Indicator],
    ):
        self.improvement = improvement
        self.quality = quality
        self.rules = rules
        self.indicators = indicators

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Screener":
        imp, qual = cfg["improvement"], cfg["quality"]
        return cls(
            ImprovementSignal(imp["clear_threshold"], imp["same_quarter_tolerance_days"], imp["max_quarter_age_days"]),
            EpsQualityFlags(qual["max_quarter_share_of_annual"]),
            build_rules(cfg),
            build_indicators(cfg),
        )

    def screen(self, data: StockData) -> ScreenResult:
        """Compute improvement signals, run all rules (``fail_rule`` is the first failure), then the indicators."""
        metrics: dict[str, Any] = self.improvement.evaluate(data)
        metrics[F.QUALITY_FLAGS] = self.quality.evaluate(data, metrics)
        fail_rule = None
        for rule in self.rules:
            res = rule.evaluate(data, metrics)
            if not res.passed and fail_rule is None:
                fail_rule = type(rule).__name__
            metrics.update(res.metrics)

        for indicator in self.indicators:
            metrics.update(indicator.compute(data, metrics))

        if fail_rule is not None:
            return ScreenResult(False, fail_rule, metrics)

        row = {
            F.TICKER: data.ticker,
            F.NAME: data.info.get("longName", data.ticker),
            **metrics,
        }
        return ScreenResult(True, None, row)
