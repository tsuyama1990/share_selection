"""I-C9-7 (not implemented). Placeholder (L2 C9 section 11).

`tailwind-eval`: pass or fail against the answers, recorded, `watch` refused without a pass.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-7: src/tailwind.py not implemented")
def test_module_exists():
    importlib.import_module("src.tailwind")
