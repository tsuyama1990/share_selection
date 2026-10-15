"""Stage 5: flags on a quarterly-EPS improvement that may come from one-off gains or losses."""

from dataclasses import dataclass
from typing import Any

from . import fields as F
from .metrics import latest_valid_period, to_num
from .stock_data import StockData


@dataclass
class EpsQualityFlags:
    """Flag quarterly-EPS clear improvements with falling annual operating income or a one-quarter EPS spike."""

    max_quarter_share_of_annual: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> list[str]:
        # Only quarterly-decided clears: then EPS_Q_Latest is always present.
        if metrics[F.IMPROVEMENT_CLASS] != F.CLASS_CLEAR or metrics.get(F.IMPROVEMENT_SOURCE) != F.SOURCE_QUARTERLY:
            return []
        flags = []
        oi_yoy = to_num(metrics.get(F.OI_YOY))
        if oi_yoy is not None and oi_yoy < 0:
            flags.append("oi_divergence")
        annual = self._annual_eps(data)
        if annual is not None and annual > 0 and metrics[F.EPS_Q_LATEST] >= self.max_quarter_share_of_annual * annual:
            flags.append("quarter_spike")
        return flags

    @staticmethod
    def _annual_eps(data: StockData) -> float | None:
        i = latest_valid_period(data.financials, ("Diluted EPS",))
        return None if i is None else to_num(data.financials.loc["Diluted EPS"].iloc[i])
