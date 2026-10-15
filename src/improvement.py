"""Stage 2: signs of improvement (quarterly EPS and annual operating income vs a year earlier)."""

from dataclasses import dataclass
from typing import Any

from . import fields as F
from .metrics import annual_operating_change, quarterly_eps_pair, to_num
from .stock_data import StockData

# Growth rates are compared at the 0.1% precision of the reported columns (12 / 10 - 1 must count as 20%).
YOY_DECIMALS = 3
# Quarterly EPS change is annualized to compare with the yearly operating-income fallback.
QUARTERS_PER_YEAR = 4


@dataclass
class ImprovementSignal:
    """Quarterly EPS decides (turnaround = clear), else annual operating income: clear >= threshold, signal >= 0."""

    clear_threshold: float
    same_quarter_tolerance_days: int
    max_quarter_age_days: int

    def evaluate(self, data: StockData) -> dict[str, Any]:
        out: dict[str, Any] = {}
        latest = eps_yoy = eps_delta = None
        pair = quarterly_eps_pair(data.quarterly_income, self.same_quarter_tolerance_days)
        if pair is not None:
            latest, date, prev = pair
            out.update(
                {F.EPS_Q_LATEST: latest, F.EPS_Q_LATEST_DATE: date.strftime("%Y-%m-%d"), F.EPS_Q_PREV_YEAR: prev}
            )
            # A latest quarter far older than the price data means newer quarters are missing: do not judge on it.
            as_of = None if data.history.empty else data.history.index.max()
            if prev is not None and (as_of is None or (as_of - date).days <= self.max_quarter_age_days):
                eps_delta = latest - prev
                eps_yoy = round(latest / prev - 1, YOY_DECIMALS) if prev > 0 else None
        oi_yoy, margin_change, oi_delta = annual_operating_change(data.financials)
        oi_yoy = None if oi_yoy is None else round(oi_yoy, YOY_DECIMALS)
        out[F.EPS_Q_YOY] = None if eps_yoy is None else round(eps_yoy * 100, 1)
        out[F.OI_YOY] = None if oi_yoy is None else round(oi_yoy * 100, 1)
        out[F.OP_MARGIN_CHANGE] = None if margin_change is None else round(margin_change, 1)
        delta: float | None
        if latest is not None and eps_delta is not None:  # quarterly EPS decides
            out[F.IMPROVEMENT_CLASS] = self._classify_quarter(latest, eps_delta, eps_yoy)
            out[F.IMPROVEMENT_SOURCE] = F.SOURCE_QUARTERLY
            delta, base = eps_delta * QUARTERS_PER_YEAR, to_num(data.fast_info.get("last_price"))
        else:
            out[F.IMPROVEMENT_CLASS] = self._classify_growth(oi_yoy)
            out[F.IMPROVEMENT_SOURCE] = None if oi_yoy is None else F.SOURCE_ANNUAL
            delta, base = oi_delta, to_num(data.fast_info.get("market_cap"))
        out[F.IMPROVEMENT_YIELD] = None if delta is None or not base else round(delta / base * 100, 2)
        return out

    def _classify_quarter(self, latest: float, delta: float, eps_yoy: float | None) -> str:
        """Turnaround -> clear; with a loss a year earlier (no YoY %), a narrower loss -> signal."""
        if eps_yoy is None:
            return F.CLASS_CLEAR if latest > 0 else F.CLASS_SIGNAL if delta > 0 else F.CLASS_NONE
        return self._classify_growth(eps_yoy)

    def _classify_growth(self, growth: float | None) -> str:
        if growth is None:
            return F.CLASS_UNKNOWN
        if growth >= self.clear_threshold:
            return F.CLASS_CLEAR
        return F.CLASS_SIGNAL if growth >= 0 else F.CLASS_NONE
