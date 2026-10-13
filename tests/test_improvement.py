import pandas as pd
import pytest

from src.improvement import ImprovementSignal
from src.stock_data import StockData

SIGNAL = ImprovementSignal(clear_threshold=0.20, same_quarter_tolerance_days=20)


def quarterly(**eps: float | None) -> pd.DataFrame:
    return pd.DataFrame({date: {"Diluted EPS": v} for date, v in eps.items()})


def annual(oi: float, oi_prev: float, rev: float = 100.0, rev_prev: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "2025": {"Total Revenue": rev, "Operating Income": oi},
            "2024": {"Total Revenue": rev_prev, "Operating Income": oi_prev},
        }
    )


def evaluate(quarterly_income=None, financials=None):
    data = StockData.from_dict("1.T", {"quarterly_income": quarterly_income, "financials": financials})
    return SIGNAL.evaluate(data)


def q(latest: float, prev: float | None, prev_date: str = "2024-12-31") -> pd.DataFrame:
    return quarterly(**{"2025-12-31": latest, prev_date: prev})


@pytest.mark.parametrize(
    ("latest", "prev", "expected"),
    [
        (12.0, 10.0, "clear"),
        (11.99, 10.0, "signal"),
        (10.0, 10.0, "signal"),
        (9.0, 10.0, "none"),
        (5.0, 0.0, "clear"),
        (5.0, -2.0, "clear"),
    ],
)
def test_eps_class_boundaries(latest, prev, expected):
    assert evaluate(q(latest, prev))["Improvement_Class"] == expected


def test_eps_metrics_and_raw_values():
    out = evaluate(q(12.0, 10.0))
    assert (out["EPS_Q_Latest"], out["EPS_Q_Latest_Date"], out["EPS_Q_Prev_Year"], out["EPS_Q_YoY(%)"]) == (
        12.0,
        "2025-12-31",
        10.0,
        20.0,
    )


def test_turnaround_has_no_yoy_percentage():
    out = evaluate(q(5.0, -2.0))
    assert out["EPS_Q_YoY(%)"] is None
    assert out["EPS_Q_Prev_Year"] == -2.0


def test_missing_prev_year_is_unknown_but_keeps_latest():
    out = evaluate(quarterly(**{"2025-12-31": 5.0}))
    assert (out["Improvement_Class"], out["EPS_Q_Latest"], out["EPS_Q_Prev_Year"]) == ("unknown", 5.0, None)


@pytest.mark.parametrize(
    ("prev_date", "found"), [("2024-12-11", True), ("2025-01-20", True), ("2024-12-10", False), ("2025-01-21", False)]
)
def test_same_quarter_tolerance_window_edges(prev_date, found):
    # 2025-12-31 minus 365 days = 2024-12-31; tolerance 20 days -> 2024-12-11 .. 2025-01-20
    assert (evaluate(q(12.0, 10.0, prev_date))["EPS_Q_Prev_Year"] is not None) is found


def test_latest_is_newest_non_nan_column():
    out = evaluate(quarterly(**{"2026-03-31": None, "2025-12-31": 12.0, "2024-12-31": 10.0}))
    assert (out["EPS_Q_Latest_Date"], out["EPS_Q_YoY(%)"]) == ("2025-12-31", 20.0)


def test_operating_income_growth_and_margin_change():
    out = evaluate(financials=annual(oi=24.0, oi_prev=20.0, rev=100.0, rev_prev=160.0))
    assert (out["OI_YoY(%)"], out["Op_Margin_Change(pt)"], out["Improvement_Class"]) == (20.0, 11.5, "clear")


def test_operating_income_prev_not_positive_gives_no_yoy():
    out = evaluate(financials=annual(oi=5.0, oi_prev=-1.0))
    assert (out["OI_YoY(%)"], out["Op_Margin_Change(pt)"], out["Improvement_Class"]) == (None, 6.0, "unknown")


def test_none_when_all_available_are_negative():
    out = evaluate(q(5.0, 10.0), annual(oi=10.0, oi_prev=20.0))
    assert out["Improvement_Class"] == "none"


def test_signal_when_any_available_is_non_negative():
    assert evaluate(q(5.0, 10.0), annual(oi=21.0, oi_prev=20.0))["Improvement_Class"] == "signal"


def test_all_missing_is_unknown():
    out = evaluate()
    assert out["Improvement_Class"] == "unknown"
    assert out["EPS_Q_YoY(%)"] is None and "EPS_Q_Latest" not in out
