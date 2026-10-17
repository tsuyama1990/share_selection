import datetime
from unittest import mock

import pytest

import src.records as records
from src.config import load_config

CFG = load_config()


@pytest.mark.parametrize(
    ("today", "issue"),
    [
        (datetime.date(2026, 10, 14), "2026-09"),
        (datetime.date(2026, 9, 14), "2026-06"),
        (datetime.date(2026, 9, 15), "2026-09"),
        (datetime.date(2026, 12, 15), "2026-12"),
        (datetime.date(2027, 1, 1), "2026-12"),
        (datetime.date(2027, 3, 14), "2026-12"),
        (datetime.date(2027, 3, 15), "2027-03"),
    ],
)
def test_latest_issue_boundaries(today, issue):
    rec = CFG["records"]
    assert records.latest_issue(today, rec["shikiho_issue_months"], rec["shikiho_release_day"]) == issue


def test_head_commit_none_when_unavailable():
    with mock.patch("src.records.subprocess.run", side_effect=OSError):
        assert records.git_sha() is None
