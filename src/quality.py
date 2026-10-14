"""Stage 5: flags on a quarterly-EPS improvement that may come from one-off gains or losses."""

from dataclasses import dataclass
from typing import Any

from .metrics import latest_valid_period, to_num
from .stock_data import StockData


@dataclass
class EpsQualityFlags:
    """Flag quarterly-EPS clear improvements with falling annual operating income or a one-quarter EPS spike."""

    max_quarter_share_of_annual: float

    def evaluate(self, data: StockData, metrics: dict[str, Any]) -> list[str]:
        prev, latest = to_num(metrics.get("EPS_Q_Prev_Year")), to_num(metrics.get("EPS_Q_Latest"))
        decided_by_quarter = to_num(metrics.get("EPS_Q_YoY(%)")) is not None or (prev is not None and prev <= 0)
        if metrics["Improvement_Class"] != "clear" or latest is None or not decided_by_quarter:
            return []
        flags = []
        oi_yoy = to_num(metrics.get("OI_YoY(%)"))
        if oi_yoy is not None and oi_yoy < 0:
            flags.append("oi_divergence")
        annual = self._annual_eps(data)
        if annual is not None and annual > 0 and latest >= self.max_quarter_share_of_annual * annual:
            flags.append("quarter_spike")
        return flags

    @staticmethod
    def _annual_eps(data: StockData) -> float | None:
        i = latest_valid_period(data.financials, ("Diluted EPS",))
        return None if i is None else to_num(data.financials.loc["Diluted EPS"].iloc[i])
