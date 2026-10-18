"""I-C9-8 (not implemented). Placeholder (L2 C9 section 11).

`confirm`: sales records (a quarter is not overwritten), the selection rule (growth, acceleration, flow median, ended
flows excluded), gate results copied, reviewed companies skipped, alert sections.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-8: src/tailwind.py not implemented")
def test_module_exists():
    importlib.import_module("src.tailwind")
