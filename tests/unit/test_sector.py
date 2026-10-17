import pytest

from src.sector import Peers, compare, sector_medians

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
