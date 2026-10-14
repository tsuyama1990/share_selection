"""Stage 2 priority ranking, CSV report and console summary of screening results."""

import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

CLASS_ORDER = {"clear": 0, "signal": 1, "none": 2, "unknown": 3}


def _priority_key(row: dict[str, Any]) -> tuple[int, float, float]:
    """Class, then Improvement_Yield (earnings change / price) descending, then Real_PSR ascending."""
    yield_, psr = row.get("Improvement_Yield(%)"), row.get("Real_PSR")
    return (
        CLASS_ORDER[row["Improvement_Class"]],
        float("inf") if pd.isna(yield_) else -yield_,
        float("inf") if pd.isna(psr) else psr,
    )


def prioritize(rows: list[dict[str, Any]], candidates_n: int) -> None:
    """Add Priority_Rank (1..n) and Stage2_Candidate (first ``candidates_n`` clear rows without Quality_Flags)."""
    open_slots = candidates_n
    for rank, row in enumerate(sorted(rows, key=_priority_key), start=1):
        row["Priority_Rank"] = rank
        row["Stage2_Candidate"] = open_slots > 0 and row["Improvement_Class"] == "clear" and not row["Quality_Flags"]
        open_slots -= row["Stage2_Candidate"]


def write_report(results: list[dict[str, Any]], out_dir: Path, filename: str, columns: Sequence[str]) -> Path:
    """Write results (sorted by Priority_Rank) to ``filename`` with ``{date}`` filled in, print the candidates."""
    full = pd.DataFrame(results).sort_values("Priority_Rank")
    df = full[[c for c in columns if c in full.columns]]

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename.format(date=today)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # sig for Excel

    candidates = df[full["Stage2_Candidate"]]
    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print(f"\nStage 2 Candidates ({len(candidates)}):")
    print(candidates.to_string(index=False))
    return path
