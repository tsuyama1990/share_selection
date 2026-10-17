"""CSV report and console summary of screening results."""

import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from . import fields as F


def write_failures(failures: dict[str, str], out_dir: Path, filename: str) -> Path:
    """Write the failed tickers and their errors to ``filename`` with ``{date}`` filled in."""
    path = out_dir / filename.format(date=datetime.date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(failures.items()), columns=["ticker", "error"]).to_csv(path, index=False, encoding="utf-8")
    return path


def write_report(results: list[dict[str, Any]], out_dir: Path, filename: str, columns: Sequence[str]) -> Path:
    """Write results (sorted by Priority_Rank) to ``filename`` with ``{date}`` filled in, print the candidates."""
    full = pd.DataFrame(results).sort_values(F.PRIORITY_RANK)
    df = full[[c for c in columns if c in full.columns]].copy()
    if F.QUALITY_FLAGS in df.columns:
        df[F.QUALITY_FLAGS] = df[F.QUALITY_FLAGS].map(",".join)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename.format(date=today)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # sig for Excel

    candidates = df[full[F.STAGE2_CANDIDATE]]
    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print(f"\nStage 2 Candidates ({len(candidates)}):")
    print(candidates.to_string(index=False))
    return path
