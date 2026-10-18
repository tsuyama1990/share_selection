"""E11 (not implemented). Placeholder (L1 section 7, L2 C9).

`flow-decide`, then `evaluate` on records past the period: decisions recorded, excess return and the control
(cheap laggards of the same industry) computed only for decisions past the period.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E11: flow-decide command not implemented")
def test_flow_decide_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "flow-decide", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
