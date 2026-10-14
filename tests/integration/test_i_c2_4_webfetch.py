"""I-C2-4 placeholder: the checks are listed in docs/architecture/L2_C2_data_acquisition.md section 7.

Passes (and so fails as strict xfail) once src/webfetch.py exists: replace it with the real tests then.
"""

import importlib

import pytest


@pytest.mark.xfail(strict=True, reason="I-C2-4 not implemented")
def test_module_exists():
    importlib.import_module("src.webfetch")
