"""I-C9-6 (not implemented). Placeholder (L2 C9 section 7).

`evaluate` of decisions: only decisions past the period, and the control selection.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-6: src/flow_store.py not implemented")
def test_module_exists():
    importlib.import_module("src.flow_store")
