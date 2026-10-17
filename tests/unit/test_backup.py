from datetime import datetime, timedelta

import pytest

from src.backup import BackupInsideRepoError, backup

NOW = datetime(2026, 10, 17, 9, 30, 15)
STAMP = "20261017T093015"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "memos").mkdir(parents=True)
    (root / "reviews.duckdb").write_text("db")
    (root / "memos" / "a.md").write_text("memo")
    return root


def test_copies_files_and_directories_and_reports_missing(repo, tmp_path):
    sources = [repo / "reviews.duckdb", repo / "memos", repo / "documents.duckdb"]
    snapshot = backup(sources, tmp_path / "bak", 5, repo, NOW)
    assert snapshot.path == tmp_path / "bak" / STAMP
    assert (snapshot.path / "reviews.duckdb").read_text() == "db"
    assert (snapshot.path / "memos" / "a.md").read_text() == "memo"
    assert snapshot.copied == sources[:2]
    assert snapshot.skipped == [repo / "documents.duckdb"]


def test_prunes_oldest_snapshots_and_leaves_other_folders(repo, tmp_path):
    bak = tmp_path / "bak"
    for name in ["20250101T000000", "20250102T000000", "notes", "2025"]:
        (bak / name).mkdir(parents=True)
    (bak / "readme.txt").write_text("x")
    backup([repo / "reviews.duckdb"], bak, 2, repo, NOW)
    kept = sorted(p.name for p in bak.iterdir())
    assert kept == ["2025", "20250102T000000", STAMP, "notes", "readme.txt"]


def test_keeps_the_newest_snapshots(repo, tmp_path):
    bak = tmp_path / "bak"
    for days in range(3):
        backup([repo / "reviews.duckdb"], bak, 2, repo, NOW + timedelta(days=days))
    assert len(list(bak.iterdir())) == 2


@pytest.mark.parametrize("inside", ["bak", "sub/bak"])
def test_refuses_a_backup_dir_inside_the_repo(repo, inside):
    with pytest.raises(BackupInsideRepoError):
        backup([repo / "reviews.duckdb"], repo / inside, 5, repo, NOW)
    assert not (repo / inside).exists()
