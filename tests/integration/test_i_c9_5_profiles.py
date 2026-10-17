"""I-C9-5 (not implemented). Placeholder (L2 C9 section 11).

`profiles` flow with mocked EDINET: sections stored for all tickers, failures recorded, stored reports skipped,
later `docs` skips EDINET.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-5: src/tailwind.py not implemented")
def test_module_exists():
    importlib.import_module("src.tailwind")
