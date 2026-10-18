"""I-C9-2 (not implemented). Placeholder (L2 C9 section 7).

Axis extraction: JSON check and one retry, unverified claims dropped and the axis left unknown, verified ratio.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-2: src/flow.py not implemented")
def test_module_exists():
    importlib.import_module("src.flow")
