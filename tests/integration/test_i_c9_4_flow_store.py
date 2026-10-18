"""I-C9-4 (not implemented). Placeholder (L2 C9 section 7).

Flows, axes, map and decisions recorded; inserting again adds no rows.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-4: src/flow_store.py not implemented")
def test_module_exists():
    importlib.import_module("src.flow_store")
