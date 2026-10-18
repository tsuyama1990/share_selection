"""E13 (not implemented). Placeholder (L1 section 7, L2 C9).

`confirm` (two months, fixtures for the ledger, cache and records, fake LLM): sales records added without overwriting a
quarter, only growing and accelerating companies at or above the flow median selected, gate results attached, only
passing companies reviewed, alert written, unselected pairs recorded.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E13: confirm command not implemented")
def test_confirm_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "confirm", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
