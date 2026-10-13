"""Stage 2: signs of improvement (quarterly EPS and annual operating income vs a year earlier)."""

from dataclasses import dataclass
from typing import Any

from .metrics import annual_operating_change, quarterly_eps_pair
from .stock_data import StockData

# Growth rates are compared at the 0.1% precision of the reported columns (12 / 10 - 1 must count as 20%).
YOY_DECIMALS = 3


@dataclass
class ImprovementSignal:
    """Class ``clear`` if a YoY growth >= ``clear_threshold`` or EPS turnaround, ``signal`` if >= 0."""

    clear_threshold: float
    same_quarter_tolerance_days: int

    def evaluate(self, data: StockData) -> dict[str, Any]:
        eps_yoy = turnaround = None
        out: dict[str, Any] = {}
        pair = quarterly_eps_pair(data.quarterly_income, self.same_quarter_tolerance_days)
        if pair is not None:
            latest, date, prev = pair
            out.update(
                {"EPS_Q_Latest": latest, "EPS_Q_Latest_Date": date.strftime("%Y-%m-%d"), "EPS_Q_Prev_Year": prev}
            )
            if prev is not None:
                turnaround = prev <= 0 < latest
                eps_yoy = latest / prev - 1 if prev > 0 else None
        oi_yoy, margin_change = annual_operating_change(data.financials)
        eps_yoy, oi_yoy = (None if v is None else round(v, YOY_DECIMALS) for v in (eps_yoy, oi_yoy))
        out["EPS_Q_YoY(%)"] = None if eps_yoy is None else round(eps_yoy * 100, 1)
        out["OI_YoY(%)"] = None if oi_yoy is None else round(oi_yoy * 100, 1)
        out["Op_Margin_Change(pt)"] = None if margin_change is None else round(margin_change, 1)
        out["Improvement_Class"] = self._classify(eps_yoy, oi_yoy, turnaround)
        return out

    def _classify(self, eps_yoy: float | None, oi_yoy: float | None, turnaround: bool | None) -> str:
        known = [v for v in (eps_yoy, oi_yoy) if v is not None]
        if turnaround or any(v >= self.clear_threshold for v in known):
            return "clear"
        if any(v >= 0 for v in known):
            return "signal"
        return "none" if known else "unknown"
