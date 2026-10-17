"""E9 (not implemented). Placeholder (L1 section 7, L2 C9).

`watch` (one week, sources/EDINET/LLM mocked): new items only, events only for demand-changing items, unverified
fields empty, gate results on mapped companies, alert lists only high-confidence events lasting 6+ months, no
request outside the allow list, rerun adds no rows, no key in outputs.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E9: watch command not implemented")
def test_watch_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "watch", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
