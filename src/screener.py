"""Screener: runs gatekeeper rules, then scorers, and assembles the result row."""

from typing import Any, NamedTuple

from .improvement import ImprovementSignal
from .rules import Rule, build_rules
from .scorers import Scorer, build_scorers
from .stock_data import StockData


class ScreenResult(NamedTuple):
    """Stage-1 outcome: ``row`` is the full result row if passed, else the metrics computed before ``fail_rule``."""

    passed: bool
    fail_rule: str | None
    row: dict[str, Any]


class Screener:
    """Evaluate stocks with injected rules and scorers."""

    def __init__(
        self,
        improvement: ImprovementSignal,
        rules: list[Rule],
        scorers: list[Scorer],
        quality_growth_min_growth_score: int,
        quality_value_min_value_score: int,
    ):
        self.improvement = improvement
        self.rules = rules
        self.scorers = scorers
        self.quality_growth_min_growth_score = quality_growth_min_growth_score
        self.quality_value_min_value_score = quality_value_min_value_score

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Screener":
        rec, imp = cfg["recommendation"], cfg["improvement"]
        return cls(
            ImprovementSignal(imp["clear_threshold"], imp["same_quarter_tolerance_days"]),
            build_rules(cfg),
            build_scorers(cfg),
            rec["quality_growth_min_growth_score"],
            rec["quality_value_min_value_score"],
        )

    def screen(self, data: StockData) -> ScreenResult:
        """Compute improvement signals, run the rules (first failure rejects), then the scorers."""
        metrics: dict[str, Any] = self.improvement.evaluate(data)
        for rule in self.rules:
            res = rule.evaluate(data, metrics)
            if not res.passed:
                return ScreenResult(False, type(rule).__name__, metrics)
            metrics.update(res.metrics)

        scores = {"Growth": 0, "Value": 0, "Safety": 0}
        net_net = False
        for scorer in self.scorers:
            score = scorer.score(data, metrics)
            scores[score.category] += score.points
            metrics.update(score.metrics)
            net_net = net_net or score.recommendation == "NET-NET"

        growth, value, safety = scores["Growth"], scores["Value"], scores["Safety"]
        if net_net:
            rec = "NET-NET"
        elif growth >= self.quality_growth_min_growth_score:
            rec = "Quality Growth"
        elif value >= self.quality_value_min_value_score:
            rec = "Quality Value"
        else:
            rec = "Watch"

        row = {
            "Ticker": data.ticker,
            "Name": data.info.get("longName", data.ticker),
            "Total_Score": growth + value + safety,
            "Recommendation_Type": rec,
            **metrics,
        }
        return ScreenResult(True, None, row)
