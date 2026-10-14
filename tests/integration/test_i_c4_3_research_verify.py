"""Placeholder for I-C4-3 (research.py＋verify.py＋モックの LLM) (no network)."""

import importlib

import pytest

PLANNED = "src.research"
FUNCTION = "run_task"


def planned():
    return getattr(importlib.import_module(PLANNED), FUNCTION)


@pytest.mark.xfail(strict=True, reason="I-C4-3 not implemented")
def test_json_validation_and_one_retry():
    """JSON の検証と 1 回の再依頼"""
    planned()
    raise AssertionError("I-C4-3: json_validation_and_one_retry not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-3 not implemented")
def test_drops_unverified_claims():
    """引用の照合で捨てる主張"""
    planned()
    raise AssertionError("I-C4-3: drops_unverified_claims not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-3 not implemented")
def test_replaces_with_unknown():
    """unknown への置き換え"""
    planned()
    raise AssertionError("I-C4-3: replaces_with_unknown not implemented")


@pytest.mark.xfail(strict=True, reason="I-C4-3 not implemented")
def test_verified_ratio():
    """照合率"""
    planned()
    raise AssertionError("I-C4-3: verified_ratio not implemented")
