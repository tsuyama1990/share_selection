"""I-C4-5 placeholder: the checks are listed in docs/architecture/L2_C4_stage2_research.md section 8.

Passes (and so fails as strict xfail) once src/review_eval.py exists: replace it with the real tests then.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C4-5 not implemented")
def test_module_exists():
    importlib.import_module("src.review_eval")
