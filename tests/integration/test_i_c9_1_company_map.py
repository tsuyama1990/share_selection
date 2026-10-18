"""I-C9-1 (not implemented). Placeholder (L2 C9 section 7).

Search ranks the right company within top_k; unverified "sells to" claims are not mapped; other companies'
documents are not used.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-1: src/company_map.py not implemented")
def test_module_exists():
    importlib.import_module("src.company_map")
