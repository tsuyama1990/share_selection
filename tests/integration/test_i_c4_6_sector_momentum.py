"""I-C4-6 (not implemented). Placeholder (L2 C4 section 8).

Industry momentum: 3-month industry excess return, rank and position in the industry; null when the history is short;
memo note.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C4-6: sector momentum not implemented")
def test_momentum_function_exists():
    assert hasattr(importlib.import_module("src.sector"), "momentum")
