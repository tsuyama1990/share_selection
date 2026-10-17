"""E12 (not implemented). Placeholder (L1 section 7, L2 C9).

`tailwind-eval` with a fake LLM, then `watch`: result recorded, `watch` refused (exit 1) without a passed eval for
the prompt version.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E12: tailwind-eval command not implemented")
def test_tailwind_eval_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "tailwind-eval", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
