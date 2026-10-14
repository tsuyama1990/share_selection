"""Placeholder for I-C4-4 (review の 1 銘柄分（文書ストア・LLM・記録）) (no network)."""

import importlib

import pytest

PLANNED = "src.research"
FUNCTION = "review_ticker"


def planned():
    return getattr(importlib.import_module(PLANNED), FUNCTION)


@pytest.mark.xfail(strict=True, reason="I-C4-4 not implemented")
def test_one_reviews_row():
    """reviews に 1 行"""
    planned()
    raise AssertionError("I-C4-4: one_reviews_row not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-4 not implemented")
def test_only_verified_evidence():
    """照合できた根拠だけが残る"""
    planned()
    raise AssertionError("I-C4-4: only_verified_evidence not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-4 not implemented")
def test_failure_is_status_and_continues():
    """失敗は状態として残り次へ進む"""
    planned()
    raise AssertionError("I-C4-4: failure_is_status_and_continues not implemented")
