"""Stage 2: signs of improvement (quarterly EPS and annual operating income vs a year earlier)."""

from dataclasses import dataclass
from typing import Any

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

    def evaluate(self, data: StockData) -> dict[str, Any]:
        out: dict[str, Any] = {}
        eps_yoy = eps_delta = None
        pair = quarterly_eps_pair(data.quarterly_income, self.same_quarter_tolerance_days)
        if pair is not None:
            latest, date, prev = pair
            out.update(
                {"EPS_Q_Latest": latest, "EPS_Q_Latest_Date": date.strftime("%Y-%m-%d"), "EPS_Q_Prev_Year": prev}
            )
            if prev is not None:
                eps_delta = latest - prev
                eps_yoy = round(latest / prev - 1, YOY_DECIMALS) if prev > 0 else None
        oi_yoy, margin_change, oi_delta = annual_operating_change(data.financials)
        oi_yoy = None if oi_yoy is None else round(oi_yoy, YOY_DECIMALS)
        out["EPS_Q_YoY(%)"] = None if eps_yoy is None else round(eps_yoy * 100, 1)
        out["OI_YoY(%)"] = None if oi_yoy is None else round(oi_yoy * 100, 1)
        out["Op_Margin_Change(pt)"] = None if margin_change is None else round(margin_change, 1)
        if pair is not None and pair[2] is not None:
            out["Improvement_Class"] = self._classify_quarter(pair[0], pair[2], eps_yoy)
            price = to_num(data.fast_info.get("last_price"))
            yield_ = eps_delta * QUARTERS_PER_YEAR / price if eps_delta is not None and price else None
        else:
            out["Improvement_Class"] = self._classify_growth(oi_yoy)
            mcap = to_num(data.fast_info.get("market_cap"))
            yield_ = oi_delta / mcap if oi_delta is not None and mcap else None
        out["Improvement_Yield(%)"] = None if yield_ is None else round(yield_ * 100, 2)
        return out

    def _classify_quarter(self, latest: float, prev: float, eps_yoy: float | None) -> str:
        """Quarterly EPS decides: turnaround -> clear; with a loss a year earlier, a narrower loss -> signal."""
        if prev <= 0:
            return "clear" if latest > 0 else "signal" if latest > prev else "none"
        return self._classify_growth(eps_yoy)

    def _classify_growth(self, growth: float | None) -> str:
        if growth is None:
            return "unknown"
        if growth >= self.clear_threshold:
            return "clear"
        return "signal" if growth >= 0 else "none"
