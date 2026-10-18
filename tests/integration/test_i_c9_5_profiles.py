"""I-C9-5 (not implemented). Placeholder (L2 C9 section 7).

`profiles` (collect.py) with mocked EDINET: sections stored for all tickers, failures recorded, stored reports
skipped. Placeholder keyed to the C9 store until the flow is built.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-5: src/flow_store.py not implemented")
def test_module_exists():
    importlib.import_module("src.flow_store")
