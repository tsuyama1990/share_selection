"""I-C9-4 (not implemented). Placeholder (L2 C9 section 11).

Search ranks the right company within top_k, unverified "sells to" claims make no pair, other companies' documents
unused.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-4: src/company_map.py not implemented")
def test_module_exists():
    importlib.import_module("src.company_map")
