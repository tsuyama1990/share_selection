"""I-C9-2 (not implemented). Placeholder (L2 C9 section 11).

JSON check and one retry, unverified fields unknown, irrelevant items make no event, confidence and duration rules.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C9-2: src/triage.py not implemented")
def test_module_exists():
    importlib.import_module("src.triage")
