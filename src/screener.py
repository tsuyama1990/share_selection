"""Screener: runs gatekeeper rules, then scorers, and assembles the result row."""
from typing import Any, Dict, List, Optional

from .rules import Rule, build_rules
from .scorers import Scorer, build_scorers
from .stock_data import StockData


class Screener:
    """Evaluate stocks with injected rules and scorers."""

    def __init__(self, rules: List[Rule], scorers: List[Scorer],
                 quality_growth_min_growth_score: int, quality_value_min_value_score: int):
        """
        Parameters
        ----------
        rules : List[Rule]
            Gatekeeper rules, run in order; the first failure rejects the stock.
        scorers : List[Scorer]
            Scoring criteria, run for stocks that pass every rule.
        quality_growth_min_growth_score : int
            Growth score needed for 'Quality Growth'.
        quality_value_min_value_score : int
            Value score needed for 'Quality Value'.
        """
        self.rules = rules
        self.scorers = scorers
        self.quality_growth_min_growth_score = quality_growth_min_growth_score
        self.quality_value_min_value_score = quality_value_min_value_score

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> 'Screener':
        """Build a Screener from the loaded configuration."""
        rec = cfg['recommendation']
        return cls(build_rules(cfg), build_scorers(cfg),
                   rec['quality_growth_min_growth_score'], rec['quality_value_min_value_score'])

    def evaluate(self, data: StockData) -> Optional[Dict[str, Any]]:
        """
        Screen one stock.

        Parameters
        ----------
        data : StockData
            The stock's raw data.

        Returns
        -------
        Optional[Dict[str, Any]]
            Result row if the stock passes all rules, else None.
        """
        metrics: Dict[str, Any] = {}
        for rule in self.rules:
            res = rule.evaluate(data, metrics)
            if not res.passed:
                return None
            metrics.update(res.metrics)

        scores = {'Growth': 0, 'Value': 0, 'Safety': 0}
        net_net = False
        for scorer in self.scorers:
            res = scorer.score(data, metrics)
            scores[res.category] += res.points
            metrics.update(res.metrics)
            net_net = net_net or res.recommendation == 'NET-NET'

        growth, value, safety = scores['Growth'], scores['Value'], scores['Safety']
        if net_net:
            rec = 'NET-NET'
        elif growth >= self.quality_growth_min_growth_score:
            rec = 'Quality Growth'
        elif value >= self.quality_value_min_value_score:
            rec = 'Quality Value'
        else:
            rec = 'Watch'

        return {
            'Ticker': data.ticker,
            'Name': data.info.get('longName', data.ticker),
            'Total_Score': growth + value + safety,
            'Recommendation_Type': rec,
            'Score_Growth': growth,
            'Score_Value': value,
            'Score_Safety': safety,
            **metrics,
        }
