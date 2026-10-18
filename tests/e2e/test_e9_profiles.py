"""E9 (not implemented). Placeholder (L1 section 7, L2 C9).

`profiles` with EDINET mocked (some failures): business sections stored per ticker, failures recorded without
stopping, second run skips stored reports.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E9: profiles command not implemented")
def test_profiles_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "profiles", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
