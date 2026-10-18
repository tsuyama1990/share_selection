"""E9 (not implemented). Placeholder (L1 section 7, L2 C9).

`watch` (one week, sources/EDINET/LLM mocked): new items only, events only for demand-changing items, unverified fields
empty, same case number joins the same flow and other assignments become candidates, mapped companies, the watch list
is written (not a buy signal), no request outside the allow list, rerun adds no rows, no key in outputs.
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
