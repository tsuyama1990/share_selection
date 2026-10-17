"""E8 (not implemented): `backup` copies the git-ignored records out of the repository. Placeholder."""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E8: backup command not implemented")
def test_backup_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "backup", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
