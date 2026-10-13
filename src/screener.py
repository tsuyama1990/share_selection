"""Screener: runs gatekeeper rules, then scorers, and assembles the result row."""

from typing import Any

from .rules import Rule, build_rules
from .scorers import Scorer, build_scorers
from .stock_data import StockData


class Screener:
    """Evaluate stocks with injected rules and scorers."""

    def __init__(
        self,
        rules: list[Rule],
        scorers: list[Scorer],
        quality_growth_min_growth_score: int,
        quality_value_min_value_score: int,
    ):
        self.rules = rules
        self.scorers = scorers
        self.quality_growth_min_growth_score = quality_growth_min_growth_score
        self.quality_value_min_value_score = quality_value_min_value_score

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Screener":
        rec = cfg["recommendation"]
        return cls(
            build_rules(cfg),
            build_scorers(cfg),
            rec["quality_growth_min_growth_score"],
            rec["quality_value_min_value_score"],
        )

    def evaluate(self, data: StockData) -> dict[str, Any] | None:
        """Result row if the stock passes every rule (first failure rejects), else None."""
        metrics: dict[str, Any] = {}
        for rule in self.rules:
            res = rule.evaluate(data, metrics)
            if not res.passed:
                return None
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

        return {
            "Ticker": data.ticker,
            "Name": data.info.get("longName", data.ticker),
            "Total_Score": growth + value + safety,
            "Recommendation_Type": rec,
            **metrics,
        }
