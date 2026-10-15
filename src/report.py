"""Stage 2 priority ranking, CSV report and console summary of screening results."""

import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from .fields import (
    CLASS_CLEAR,
    CLASS_NONE,
    CLASS_SIGNAL,
    CLASS_UNKNOWN,
    IMPROVEMENT_CLASS,
    IMPROVEMENT_YIELD,
    PRIORITY_RANK,
    QUALITY_FLAGS,
    REAL_PSR,
    STAGE2_CANDIDATE,
)

CLASS_ORDER = {CLASS_CLEAR: 0, CLASS_SIGNAL: 1, CLASS_NONE: 2, CLASS_UNKNOWN: 3}


def _priority_key(row: dict[str, Any]) -> tuple[int, float, float]:
    """Class, then Improvement_Yield (earnings change / price) descending, then Real_PSR ascending."""
    yield_, psr = row.get(IMPROVEMENT_YIELD), row.get(REAL_PSR)
    return (
        CLASS_ORDER[row[IMPROVEMENT_CLASS]],
        float("inf") if pd.isna(yield_) else -yield_,
        float("inf") if pd.isna(psr) else psr,
    )


def prioritize(rows: list[dict[str, Any]], candidates_n: int) -> None:
    """Add Priority_Rank (1..n) and Stage2_Candidate (first ``candidates_n`` clear rows without Quality_Flags)."""
    open_slots = candidates_n
    for rank, row in enumerate(sorted(rows, key=_priority_key), start=1):
        row[PRIORITY_RANK] = rank
        row[STAGE2_CANDIDATE] = open_slots > 0 and row[IMPROVEMENT_CLASS] == CLASS_CLEAR and not row[QUALITY_FLAGS]
        open_slots -= row[STAGE2_CANDIDATE]


def write_report(results: list[dict[str, Any]], out_dir: Path, filename: str, columns: Sequence[str]) -> Path:
    """Write results (sorted by Priority_Rank) to ``filename`` with ``{date}`` filled in, print the candidates."""
    full = pd.DataFrame(results).sort_values(PRIORITY_RANK)
    df = full[[c for c in columns if c in full.columns]].copy()
    if QUALITY_FLAGS in df.columns:
        df[QUALITY_FLAGS] = df[QUALITY_FLAGS].map(",".join)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename.format(date=today)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # sig for Excel

    candidates = df[full[STAGE2_CANDIDATE]]
    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print(f"\nStage 2 Candidates ({len(candidates)}):")
    print(candidates.to_string(index=False))
    return path
