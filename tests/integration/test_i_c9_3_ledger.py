"""I-C9-3 (not implemented). Placeholder (L2 C9 section 11).

Call and result with the same case number make one event with stages and dates, idempotent, candidate links not
merged, Parquet export.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-3: src/ledger.py not implemented")
def test_module_exists():
    importlib.import_module("src.ledger")
