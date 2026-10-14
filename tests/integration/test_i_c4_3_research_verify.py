"""I-C4-3 placeholder: the checks are listed in docs/architecture/L2_C4_stage2_research.md section 8.

Passes (and so fails as strict xfail) once src/verify.py exists: replace it with the real tests then.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C4-3 not implemented")
def test_module_exists():
    importlib.import_module("src.verify")
