import pandas as pd
import pytest

from src.quality import EpsQualityFlags
from src.stock_data import StockData

QUALITY = EpsQualityFlags(max_quarter_share_of_annual=0.5)


def flags(annual_eps=100.0, **overrides):
    financials = None if annual_eps is None else pd.DataFrame({"2025": {"Diluted EPS": annual_eps}})
    data = StockData.from_dict("1.T", {"financials": financials})
    metrics = {
        "Improvement_Class": "clear",
        "Improvement_Source": "quarterly",
        "EPS_Q_Latest": 10.0,
        "EPS_Q_Prev_Year": 5.0,
        "EPS_Q_YoY(%)": 100.0,
        "OI_YoY(%)": 10.0,
    } | overrides
    return QUALITY.evaluate(data, metrics)


def test_clean_clear_has_no_flags():
    assert flags() == []


@pytest.mark.parametrize(("oi_yoy", "expected"), [(-0.1, ["oi_divergence"]), (0.0, []), (None, [])])
def test_oi_divergence_boundary(oi_yoy, expected):
    assert flags(**{"OI_YoY(%)": oi_yoy}) == expected


@pytest.mark.parametrize(("latest", "expected"), [(50.0, ["quarter_spike"]), (49.9, []), (80.0, ["quarter_spike"])])
def test_quarter_spike_boundary_is_inclusive(latest, expected):
    assert flags(EPS_Q_Latest=latest) == expected


@pytest.mark.parametrize("annual_eps", [0.0, -20.0, None])
def test_no_spike_flag_without_positive_annual_eps(annual_eps):
    assert flags(annual_eps=annual_eps) == []


def test_both_flags():
    assert flags(EPS_Q_Latest=60.0, **{"OI_YoY(%)": -5.0}) == ["oi_divergence", "quarter_spike"]


@pytest.mark.parametrize("cls", ["signal", "none", "unknown"])
def test_non_clear_never_flagged(cls):
    assert flags(Improvement_Class=cls, EPS_Q_Latest=90.0, **{"OI_YoY(%)": -50.0}) == []


def test_annual_decided_clear_never_flagged():
    # e.g. a stale latest quarter: improvement fell back to annual even though raw quarterly EPS is recorded
    assert flags(Improvement_Source="annual", EPS_Q_Latest=90.0, **{"OI_YoY(%)": -50.0}) == []


def test_loss_year_ago_turnaround_is_quarter_decided():
    assert flags(EPS_Q_Prev_Year=-3.0, EPS_Q_Latest=60.0, **{"EPS_Q_YoY(%)": None}) == ["quarter_spike"]


def test_annual_eps_uses_latest_non_nan_column():
    data = StockData.from_dict(
        "1.T", {"financials": pd.DataFrame({"2025": {"Diluted EPS": float("nan")}, "2024": {"Diluted EPS": 100.0}})}
    )
    metrics = {
        "Improvement_Class": "clear",
        "Improvement_Source": "quarterly",
        "EPS_Q_Latest": 50.0,
        "EPS_Q_Prev_Year": 1.0,
        "EPS_Q_YoY(%)": 9.0,
    }
    assert QUALITY.evaluate(data, metrics) == ["quarter_spike"]
