"""Placeholder for I-C4-2 (sector.py と実行記録) (no network)."""

import importlib

import pytest

PLANNED = "src.sector"
FUNCTION = "sector_medians"


def planned():
    return getattr(importlib.import_module(PLANNED), FUNCTION)


@pytest.mark.xfail(strict=True, reason="I-C4-2 not implemented")
def test_sector_medians():
    """業種ごとの中央値"""
    planned()
    raise AssertionError("I-C4-2: sector_medians not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-2 not implemented")
def test_peer_comparison():
    """候補の同業比較"""
    planned()
    raise AssertionError("I-C4-2: peer_comparison not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-2 not implemented")
def test_few_peers():
    """同業が少ない業種の扱い"""
    planned()
    raise AssertionError("I-C4-2: few_peers not implemented")
