"""E6 (not implemented): `review` records LLM research on stage 2 candidates. Placeholder until C4 stage 2 exists."""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E6: C4 stage 2 review not implemented")
def test_review_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "review", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
