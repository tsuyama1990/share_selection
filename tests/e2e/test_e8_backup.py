"""E8: `backup` copies the git-ignored records to a timestamped folder outside the repository."""

import pytest

from tests.fixtures.config import CFG

SOURCES = {
    "reviews.duckdb": "reviews",
    "reviews/reviews.parquet": "export",
    "results/memos/m.md": "memo",
    "flow.duckdb": "flows",  # human decisions: not recoverable
    "results/flows/f.md": "flow memo",
}
KEEP = 2


@pytest.fixture
def seeded(project):
    for rel, text in {**SOURCES, "documents.duckdb": "docs"}.items():
        path = project.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return project


def backup_cfg(directory) -> dict:
    return {**CFG, "backup": {"dir": str(directory), "keep": KEEP}}


def test_copies_the_six_sources_and_prunes_old_snapshots(seeded, tmp_path_factory, capsys):
    outside = tmp_path_factory.mktemp("outside")
    old = [outside / f"2025010{n}T000000" for n in range(1, 4)]
    for folder in old:
        folder.mkdir()
    seeded.run("backup", cfg=backup_cfg(outside))
    snapshots = sorted(p for p in outside.iterdir() if p not in old)
    assert len(snapshots) == 1
    for rel in [*SOURCES, "documents.duckdb"]:
        assert (snapshots[0] / rel).exists()
    assert sorted(outside.iterdir()) == [*old[-(KEEP - 1) :], *snapshots]
    assert f"Backed up 6 sources to {snapshots[0]}." in capsys.readouterr().out


def test_missing_sources_are_reported(project, tmp_path_factory, capsys):
    project.run("backup", cfg=backup_cfg(tmp_path_factory.mktemp("outside")))
    out = capsys.readouterr().out
    assert "Backed up 0 sources" in out and out.count("Skipped (missing)") == 6


def test_refuses_a_backup_dir_inside_the_repo(seeded, capsys):
    with pytest.raises(SystemExit) as exit_info:
        seeded.run("backup", cfg=backup_cfg(seeded.root / "bak"))
    assert exit_info.value.code == 1
    assert capsys.readouterr().out == "Error: backup.dir must be outside the repository (it is public).\n"
    assert not (seeded.root / "bak").exists()
