"""E7 (not implemented): `docs` stores the stage 2 candidates' documents. Placeholder until the command exists."""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E7: docs command not implemented")
def test_docs_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "docs", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
