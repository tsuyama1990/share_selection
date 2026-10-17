"""I-C9-1 (not implemented). Placeholder (L2 C9 section 11).

RSS and case pages of e-Gov, the cabinet agenda list, attached PDF text, allow list, per-item failures.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-1: src/govfeed.py not implemented")
def test_module_exists():
    importlib.import_module("src.govfeed")
