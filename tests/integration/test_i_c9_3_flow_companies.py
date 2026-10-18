"""I-C9-3 (not implemented). Placeholder (L2 C9 section 7).

Per-company facts: gate result, failed rule, valuations, industry medians and 3-month position match the records.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-3: src/flow.py not implemented")
def test_module_exists():
    importlib.import_module("src.flow")
