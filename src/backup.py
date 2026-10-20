"""Timestamped copies of the git-ignored records into a folder outside the (public) repository."""

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SNAPSHOT_FORMAT = "%Y%m%dT%H%M%S"
SNAPSHOT_NAME = re.compile(r"\d{8}T\d{6}")
SOURCE_KEYS = [
    ("review", "db_file"),
    ("review", "export_dir"),
    ("memo", "dir"),
    ("docstore", "db_file"),
    ("flow", "db_file"),  # the flows and the human decisions on them
    ("flow", "memo_dir"),
]


class BackupInsideRepoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    path: Path
    copied: list[Path]
    skipped: list[Path]  # sources that do not exist


def backup(sources: list[Path], backup_dir: Path, keep: int, repo_root: Path, now: datetime) -> Snapshot:
    """Copy the existing ``sources`` (below ``repo_root``) to ``backup_dir/<timestamp>``; keep the newest ``keep``."""
    if backup_dir.resolve().is_relative_to(repo_root.resolve()):
        raise BackupInsideRepoError(str(backup_dir))
    backup_dir.mkdir(parents=True, exist_ok=True)
    snapshot = backup_dir / now.strftime(SNAPSHOT_FORMAT)
    copied, skipped = [], []
    for source in sources:
        if not source.exists():
            skipped.append(source)
            continue
        target = snapshot / source.relative_to(repo_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        copied.append(source)
    snapshots = sorted(p for p in backup_dir.iterdir() if p.is_dir() and SNAPSHOT_NAME.fullmatch(p.name))
    for old in snapshots[: max(len(snapshots) - keep, 0)]:
        shutil.rmtree(old)
    return Snapshot(snapshot, copied, skipped)


def backup_from_config(cfg: dict[str, Any], root: Path, now: datetime) -> Snapshot:
    """`backup` of the review and flow records, the memos and the document store into ``backup.dir``."""
    sources = [root / cfg[section][key] for section, key in SOURCE_KEYS]
    return backup(sources, Path(cfg["backup"]["dir"]).expanduser(), cfg["backup"]["keep"], root, now)
