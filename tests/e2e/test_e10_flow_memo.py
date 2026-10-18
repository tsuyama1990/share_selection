"""E10 (not implemented). Placeholder (L1 section 7, L2 C9).

`flow-memo` with search/web/LLM mocked: five axes with verified quotes only (else unknown), map of verified
companies, per-company Value Turn results and valuations, recorded; exit 1 with guidance before `profiles`; no key.
"""

import sys

import pytest

import main


@pytest.mark.xfail(strict=True, reason="E10: flow-memo command not implemented")
def test_flow_memo_command_exists(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "flow-memo", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
