"""Stage 2 priority ranking and candidate selection."""

from typing import Any

import pandas as pd

from . import fields as F

CLASS_ORDER = {F.CLASS_CLEAR: 0, F.CLASS_SIGNAL: 1, F.CLASS_NONE: 2, F.CLASS_UNKNOWN: 3}


def _priority_key(row: dict[str, Any]) -> tuple[int, float, float]:
    """Class, then Improvement_Yield (earnings change / price) descending, then Real_PSR ascending."""
    yield_, psr = row.get(F.IMPROVEMENT_YIELD), row.get(F.REAL_PSR)
    return (
        CLASS_ORDER[row[F.IMPROVEMENT_CLASS]],
        float("inf") if pd.isna(yield_) else -yield_,
        float("inf") if pd.isna(psr) else psr,
    )


def prioritize(rows: list[dict[str, Any]], candidates_n: int) -> None:
    """Add Priority_Rank (1..n) and Stage2_Candidate (first ``candidates_n`` clear rows without Quality_Flags)."""
    open_slots = candidates_n
    for rank, row in enumerate(sorted(rows, key=_priority_key), start=1):
        row[F.PRIORITY_RANK] = rank
        row[F.STAGE2_CANDIDATE] = (
            open_slots > 0 and row[F.IMPROVEMENT_CLASS] == F.CLASS_CLEAR and not row[F.QUALITY_FLAGS]
        )
        open_slots -= row[F.STAGE2_CANDIDATE]
