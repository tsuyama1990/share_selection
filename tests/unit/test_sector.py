import datetime

import pandas as pd
import pytest

from src.sector import MomentumSettings, Peers, Universe, compare, momentum, momentum_note, sector_medians

TODAY = datetime.date(2026, 4, 1)
START = datetime.date(2026, 1, 1)
SETTINGS = MomentumSettings(3, 1 / 3, 0.5)


def _series(prices: dict[datetime.date, float]) -> pd.Series:
    return pd.Series(list(prices.values()), index=pd.to_datetime(list(prices)), dtype=float)


def _universe(prices: dict[str, dict[datetime.date, float]], sectors: dict[str, str]) -> Universe:
    return Universe(lambda ticker: _series(prices[ticker]), list(prices), sectors)


SECTORS = {"1.T": "A", "2.T": "A", "3.T": "A", "4.T": "B", "5.T": "B"}
METRICS = ["PBR", "Real_PSR"]


def test_sector_medians_take_the_median_per_sector_and_metric():
    rows = {"1.T": {"PBR": 1.0}, "2.T": {"PBR": 3.0}, "3.T": {"PBR": 2.0}, "4.T": {"PBR": 10.0}, "5.T": {"PBR": 20.0}}
    medians = sector_medians(rows, SECTORS, METRICS, min_peers=2)
    assert medians["A"]["PBR"] == 2.0 and medians["B"]["PBR"] == 15.0


def test_a_metric_with_fewer_than_min_peers_values_is_none():
    rows = {"1.T": {"PBR": 1.0, "Real_PSR": 5.0}, "2.T": {"PBR": 3.0}, "3.T": {"PBR": 2.0}}
    medians = sector_medians(rows, SECTORS, METRICS, min_peers=3)
    assert medians["A"] == {"PBR": 2.0, "Real_PSR": None}
    assert sector_medians(rows, SECTORS, METRICS, min_peers=4)["A"]["PBR"] is None


def test_missing_non_numeric_and_unsectored_values_are_ignored():
    rows = {
        "1.T": {"PBR": 1.0},
        "2.T": {"PBR": None},
        "3.T": {"PBR": "n/a"},
        "4.T": {"PBR": float("nan")},
        "5.T": {"PBR": True},
        "7.T": {"PBR": 99.0},  # no sector
    }
    medians = sector_medians(rows, SECTORS, METRICS, min_peers=1)
    assert medians["A"]["PBR"] == 1.0
    assert "B" not in medians  # no numeric value at all


PEERS = Peers({"A": {"PBR": 2.0, "Real_PSR": None}, "B": {"PBR": 0.0, "Real_PSR": 1.0}}, SECTORS, METRICS)


def test_compare_gives_value_median_and_ratio():
    result = compare("1.T", {"PBR": 3.0, "Real_PSR": 0.5}, PEERS)
    assert result["sector"] == "A"
    assert result["metrics"]["PBR"] == {"value": 3.0, "median": 2.0, "ratio": 1.5}


def test_ratio_is_none_when_the_median_is_none_or_zero_or_the_value_is_missing():
    result = compare("1.T", {"PBR": 3.0, "Real_PSR": 0.5}, PEERS)
    assert result["metrics"]["Real_PSR"] == {"value": 0.5, "median": None, "ratio": None}
    assert compare("4.T", {"PBR": 3.0}, PEERS)["metrics"]["PBR"] == {"value": 3.0, "median": 0.0, "ratio": None}
    missing = compare("4.T", {}, PEERS)["metrics"]["Real_PSR"]
    assert missing == {"value": None, "median": 1.0, "ratio": None}


def test_a_ticker_without_a_sector_has_no_medians():
    result = compare("9.T", {"PBR": 3.0}, PEERS)
    assert result["sector"] is None
    assert result["metrics"]["PBR"] == {"value": 3.0, "median": None, "ratio": None}


def test_ratio_to_a_negative_median_is_plain_division():
    peers = Peers({"A": {"PBR": -2.0}}, {"1.T": "A"}, ["PBR"])
    assert compare("1.T", {"PBR": 3.0}, peers)["metrics"]["PBR"]["ratio"] == pytest.approx(-1.5)


def test_momentum_gives_the_industry_excess_rank_and_position():
    prices = {
        "1.T": {START: 100.0, TODAY: 200.0},
        "2.T": {START: 100.0, TODAY: 100.0},
        "3.T": {START: 100.0, TODAY: 300.0},
    }
    sectors = {"1.T": "A", "2.T": "A", "3.T": "B"}
    result = momentum(_universe(prices, sectors), "1.T", SETTINGS, TODAY)
    assert result["months"] == 3
    assert result["industry_excess"] == pytest.approx(-0.5)
    assert result["industry_rank"] == 2
    assert result["industries"] == 2
    assert result["position"] == pytest.approx(0.5)


def test_momentum_uses_the_last_close_on_or_before_each_date_and_ignores_the_future():
    prices = {
        "1.T": {
            datetime.date(2025, 12, 31): 100.0,
            datetime.date(2026, 1, 1): 200.0,
            datetime.date(2026, 3, 31): 300.0,
            datetime.date(2026, 4, 2): 999.0,
        }
    }
    result = momentum(_universe(prices, {"1.T": "A"}), "1.T", SETTINGS, TODAY)
    assert result["industry_excess"] == pytest.approx(0.0)
    assert result["position"] == pytest.approx(1.0)


def test_a_ticker_without_a_close_before_the_start_is_left_out():
    prices = {
        "1.T": {START: 100.0, TODAY: 110.0},
        "2.T": {datetime.date(2026, 2, 1): 100.0, TODAY: 200.0},
    }
    result = momentum(_universe(prices, {"1.T": "A", "2.T": "A"}), "1.T", SETTINGS, TODAY)
    assert result["position"] == pytest.approx(1.0)
    assert result["industry_excess"] == pytest.approx(0.0)


def test_an_unknown_target_has_no_industry_or_position():
    prices = {"1.T": {START: 1.0, TODAY: 2.0}}
    result = momentum(_universe(prices, {"1.T": "A"}), "9.T", SETTINGS, TODAY)
    assert result == {
        "months": 3,
        "industry_excess": None,
        "industry_rank": None,
        "industries": 1,
        "position": None,
    }


def test_equal_returns_share_the_smallest_rank():
    prices = {ticker: {START: 100.0, TODAY: 200.0} for ticker in ("1.T", "2.T", "3.T", "4.T")}
    sectors = {"1.T": "A", "2.T": "A", "3.T": "B", "4.T": "B"}
    result = momentum(_universe(prices, sectors), "1.T", SETTINGS, TODAY)
    assert result["industry_rank"] == 1
    assert result["industries"] == 2
    assert result["position"] == pytest.approx(0.5)


def test_note_needs_the_top_share_and_the_lower_half():
    assert momentum_note({"industry_rank": 1, "industries": 3, "position": 0.6}, SETTINGS) is True
    assert momentum_note({"industry_rank": 1, "industries": 3, "position": 0.5}, SETTINGS) is False
    assert momentum_note({"industry_rank": 2, "industries": 3, "position": 0.6}, SETTINGS) is False
    assert momentum_note({"industry_rank": None, "industries": 3, "position": 0.6}, SETTINGS) is False
    assert momentum_note({"industry_rank": 1, "industries": 0, "position": 0.6}, SETTINGS) is False
    assert momentum_note({"industry_rank": 1, "industries": 3, "position": None}, SETTINGS) is False
