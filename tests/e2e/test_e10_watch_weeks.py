"""E10 (not implemented). Placeholder (L1 section 7, L2 C9).

Two weeks of `watch` (call for comments, then the result with the same case number; a rate turn in another week): one
flow raised to confirmed with dates, listed as strengthened when the overlap grows, ending-soon section, the rate turn
becomes an event.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E10: watch command not implemented")
def test_watch_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "watch", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
